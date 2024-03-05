import requests
import json


baseURL = "https://ipsego.app/api/v1/"

def doLogin(user: str, password: str) -> str:
    params = {
        "username": user,
        "password": password,
        "client_id": "ipseproweb_webapp",
        "grant_type":"password",
        "scope": "openid email phone profile offline_access roles ipseproweb_api"
    }
    res = requests.post("https://ipsego.app/openid/connect/token",data=params, headers=headers)
    if res.status_code != 200:
        raise ValueError(f"Error login: {res.status_code}; {res.text}")
    
    res = res.json()
    return f"Bearer {res['access_token']}"

def getProjectData(headers, projectId) -> dict:
        params = {"id": projectId}
        res = requests.get(f"{baseURL}projects", params=params, headers=headers)
        if res.status_code != 200:
            raise ValueError(f"Error getting project;{res.text};{res.status_code}")
        
        res = res.json()
        projectData = json.loads(res["content"])

        return projectData


