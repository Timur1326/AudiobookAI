import requests
import json

subscription_key = "d818daf5cc10465c92732f50f10412eb"
region = "westeurope"

url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list"
headers = {"Ocp-Apim-Subscription-Key": subscription_key}

response = requests.get(url, headers=headers)
voices = response.json()

for v in voices:
    if v["ShortName"] == "en-US-AriaNeural":
        print(json.dumps(v, indent=2))
