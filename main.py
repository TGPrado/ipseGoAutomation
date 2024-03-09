import websockets
import requests
import asyncio
import json

baseURL = "https://ipsego.app"


import time


def doLogin(user: str, password: str) -> str:
    data = {
        "username": user,
        "password": password,
        "client_id": "ipseproweb_webapp",
        "grant_type": "password",
        "scope": "openid email phone profile offline_access roles ipseproweb_api",
    }
    res = requests.post(f"{baseURL}/openid/connect/token", data=data)
    if res.status_code != 200:
        raise ValueError(f"Error login: {res.status_code}; {res.text}")

    res = res.json()
    return f"Bearer {res['access_token']}"


def getProjectData(headers: dict, projectId: str) -> dict:
    params = {"id": projectId}
    res = requests.get(f"{baseURL}/api/v1/projects", params=params, headers=headers)
    if res.status_code != 200:
        raise ValueError(f"Error getting project;{res.text};{res.status_code}")

    return res.json()


def createItemsGlobas(datasets: dict):
    items = {}
    for key, value in datasets.items():
        bounds = value["bounds"]
        items[key] = {"limit": [bounds["lower"], bounds["upper"]]}
        if value["status"] == "undefined":
            continue

        items[key].update({value["status"]: value["value"]})

    return items


def createGlobals(content: dict) -> list:
    globals = content["flowsheetObjects"]["fsGlobals"]
    globalsPayload = []
    for item in globals:
        payload = {
            "name": item["name"],
            "model": item["className"],
        }
        datasets = item["datasets"][0]["items"]
        payload["items"] = createItemsGlobas(datasets)
        globalsPayload.append(payload)

    return globalsPayload


def createConnectionsPayload(content: dict) -> list:
    connections = content["flowsheetObjects"]["fsConnections"]
    connectionsPayload = []
    for item in connections:
        payload = {"name": item["name"], "model": item["className"]}
        references = (
            {"Composition": item["references"][0]} if item["references"] != [] else {}
        )
        datasets = item["datasets"][0]["items"]
        items = {}
        if datasets:
            items = {
                key: {value["status"]: value["value"]}
                for key, value in datasets.items()
                if value["status"] != "undefined"
            }
        payload["references"] = references
        payload["items"] = items
        connectionsPayload.append(payload)
    return connectionsPayload


def createReferencesUnits(content: dict) -> dict:
    units = content["flowsheetObjects"]["fsUnits"]
    references = {}
    for item in units:
        if item["references"] == []:
            continue
        references[item["name"]] = item["references"]

    return references


def createConnectionsReferences(content: dict, unitReferences: dict) -> dict:
    connections = content["flowsheetObjects"]["fsConnections"]
    references = {}
    for item in connections:
        if not "firstTerminal" in item:
            continue

        key = item["firstTerminal"]["unitName"]
        references.setdefault(key, {}).update(
            {item["firstTerminal"]["terminalName"]: item["name"]}
        )

        if not "secondTerminal" in item:
            continue

        if "ambient_source" in key:
            references[key].update({"AmbientConditions": unitReferences[key][0]})

        key = item["secondTerminal"]["unitName"]
        references.setdefault(key, {}).update(
            {item["secondTerminal"]["terminalName"]: item["name"]}
        )
        if "ambient_source" in key:
            references[key].update({"AmbientConditions": unitReferences[key]})

    return references


def createItemsUnits(datasets: dict):
    items = {}
    if datasets == None:
        return
    for key, value in datasets.items():
        if value["type"] == "variable":
            items[key] = {"set": value["value"]}
            continue
        if value["type"] == "parameter":
            items[key] = value["value"]
            continue

    return items


def createUnitsPayload(content: dict) -> list:
    units = content["flowsheetObjects"]["fsUnits"]
    unitReferences = createReferencesUnits(content)
    connectionsReferences = createConnectionsReferences(content, unitReferences)
    unitsPayload = []
    for item in units:
        payload = {"name": item["name"], "model": item["datasets"][0]["model"]}
        datasets = item["datasets"][0]["items"]
        references = connectionsReferences[item["name"]]
        payload["items"] = createItemsUnits(datasets)
        payload["references"] = references
        unitsPayload.append(payload)

    return unitsPayload


def createThirdArgument(projectData: dict) -> dict:
    content = json.loads(projectData["content"])
    payload = {
        "LibGUID": "",
        "LibName": "",
        "Task": "stat",
        "solverParameters": {
            "bExtendedProtocol": False,
            "bUseDamping": False,
            "nSteps": 10,
            "xTolerance": 0.001,
            "yTolerance": 0.001,
        },
        "analysisOptions": {
            "bModelAnalysisEnabled": False,
            "bSettingsAnalysisEnabled": True,
        },
        "dataFrameCells": [],
    }

    payload["LibGUID"] = projectData["library"]["guid"]
    payload["LibName"] = projectData["library"]["name"]
    payload["globals"] = createGlobals(content)
    payload["connections"] = createConnectionsPayload(content)
    payload["units"] = createUnitsPayload(content)
    return payload


def prepareData(projectData: dict) -> dict:
    data = {
        "arguments": [],
        "invocationId": "1",
        "target": "RequestCalculation",
        "type": 1,
    }
    arguments = data["arguments"]
    arguments.append(projectData["id"])
    arguments.append(projectData["library"]["guid"])
    arguments.append(createThirdArgument(projectData))
    arguments.append(0)
    return data


def getDataByKeys(payload: dict) -> dict:
    data = {
        item["name"]: ["globals", payload["globals"].index(item)]
        for item in payload["globals"]
    }
    for item in payload["connections"]:
        data.update({item["name"]: ["connections", payload["connections"].index(item)]})

    for item in payload["units"]:
        data.update({item["name"]: ["units", payload["units"].index(item)]})

    return data


def changeData(newData: dict, projectData: dict) -> None:
    payload = projectData["arguments"][2]
    dataByKeys = getDataByKeys(payload)
    for key, value in newData.items():
        if key not in dataByKeys:
            continue

        local, index = dataByKeys[key]
        items = payload[local][index]["items"]
        for item in value:
            if not item in items:
                continue

            data = items[item]
            if not "set" in data:
                continue

            data["set"] = value[item]

    projectData["arguments"][2] = json.dumps(payload)


async def reqCalc(projectId: str, headers: dict) -> None:
    data = {
        "n": "run-calc",
        "u": f"{baseURL}/project/{projectId}",
        "d": "ipsego.app",
        "r": None,
        "p": {"target": "qa-menu"},
    }
    res = requests.post(
        "https://plausible.ipsego.app/api/event", json=data, headers=headers
    )
    if res.status_code != 202:
        raise ValueError(f"Error request calc;{res.text};{res.status_code}")


def getConnectionToken(headers: dict) -> str:
    res = requests.post(
        f"{baseURL}/signalr/negotiate?negotiateVersion=1", headers=headers
    )
    if res.status_code != 200:
        raise ValueError(f"Error login: {res.status_code}; {res.text}")

    res = res.json()
    return res["connectionToken"]


async def startConnectionWebSocket(
    connectionToken: str, headers: dict
) -> websockets.WebSocketClientProtocol:
    auth = headers["Authorization"].replace("Bearer ", "")
    url = f"wss://ipsego.app/signalr?id={connectionToken}&access_token={auth}"
    websocket = await websockets.connect(url)
    await websocket.send('{"protocol":"json","version":1}\x1E')
    return websocket


async def requestCalculation(
    payload: dict, websocket: websockets.WebSocketClientProtocol
) -> int:
    await websocket.send(json.dumps(payload) + "\x1E")
    while True:
        res = await websocket.recv()
        if "calculationId" in res:
            res = res[:-1]
            return json.loads(res)["result"]["calculationId"]


async def registerCalculation(
    websocket: websockets.WebSocketClientProtocol, id: int
) -> None:
    payload = {
        "arguments": [{"id": id}],
        "invocationId": "2",
        "target": "RegisterCalculation",
        "type": 1,
    }
    await websocket.send(json.dumps(payload) + "\x1E")


async def getResult(websocket: websockets.WebSocketClientProtocol) -> dict:
    data = ""
    while True:
        data = await websocket.recv()
        if '"progress":1' in data:
            data = data[:-1]
            break
    await websocket.close()
    data = json.loads(data)["arguments"][0][0]["state"]["value"]
    data = json.loads(data)
    return data["ItemResults"]


async def main():
    headers = {}
    headers["Authorization"] = doLogin("", "")
    projectData = getProjectData(headers, "")
    data = prepareData(projectData)
    newDataExample = {
        "stream005": {"p": 1.06, "k": 1.01},
        "source001": {"mass": 4.05, "t": 4.06, "k": 123},
        "ambient001": {
            "p": 0.9768,
            "altitude": 1231231,
            "t": 28,
        },
        "ambient027": {
            "p": 0.9768,
            "altitude": 1231231,
            "t": 28,
        },
    }
    changeData(newDataExample, data)
    connectionToken = getConnectionToken(headers)
    data["arguments"][2] = json.dumps(data["arguments"][2])
    websocket = await startConnectionWebSocket(connectionToken, headers)
    id = await requestCalculation(data, websocket)
    await registerCalculation(websocket, id)
    res = await getResult(websocket)


if __name__ == "__main__":
    asyncio.run(main())
