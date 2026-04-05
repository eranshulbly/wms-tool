import requests

res = requests.get('http://localhost:5000/api/warehouses')
print("NO TOKEN:", res.status_code, res.text)
