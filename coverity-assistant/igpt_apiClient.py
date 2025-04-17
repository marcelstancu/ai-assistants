import requests
import time
import logging
from proxy import Proxy
 
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
 
class IgptAPIClient:
    def __init__(
        self, client_id, client_secret, proxy_url= None, auth_url=None,
        api_url=None, api_url_stream=None, api_url_embed=None, disable_proxy=False
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.proxy_url = proxy_url if proxy_url else "http://proxy-chain.intel.com:912"
        self.auth_url = auth_url if auth_url else "https://apis-internal.intel.com/v1/auth/token"
        self.api_url = api_url if api_url else 'https://intel-prod.apigee.com/generativeaiinference/v2'
        self.api_url_stream = api_url_stream if api_url_stream else 'https://intel-prod.apigee.com/generativeaiinference/v2/stream'
        self.api_url_embed = api_url_embed if api_url_embed else 'https://apis-internal.intel.com/generativeaiembedding/v1/embed'
        self.access_token = None
        self.access_token_expires_on = None
        self.proxy = None if disable_proxy else Proxy(self.proxy_url)
 
    def get_access_token(self):
        data = {
            'grant_type': 'client_credentials'
        }
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        try:
            response = requests.post(
                self.auth_url,
                data=data,
                headers=headers,
                auth=(self.client_id, self.client_secret),
                proxies=self.proxy.proxies if self.proxy else None
            )
            response.raise_for_status()
            response_json = response.json()
            logging.info("%s", response_json)
            self.access_token_expires_on = int(response_json.get('expires_in')) + time.time() - 60
            self.access_token = response_json.get('access_token')
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to get access token: {e}")
            raise
 
    def process_request(self, json_data):
        self.check_access_token()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}"
        }
        try:
            logging.info("1.Processing request %s",self.api_url)
            response = requests.post(
                self.api_url,
                headers=headers,
                json=json_data,
                proxies=self.proxy.proxies if self.proxy else None
            )
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to process request: {e}")
            raise
 
    def process_request_stream(self, json_data):
        self.check_access_token()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}"
        }
        try:
            response = requests.post(
                self.api_url_stream,
                headers=headers,
                json=json_data,
                proxies=self.proxy.proxies if self.proxy else None,
                stream=True
            )
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=None):
                if chunk:
                    yield chunk
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to process request: {e}")
            raise
 
    def check_access_token(self):
        if self.access_token is None or (self.access_token_expires_on and self.access_token_expires_on <= time.time()):
            self.get_access_token()
 
    def process_request_embed(self, json_data):
        self.check_access_token()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}"
        }
        try:
            response = requests.post(
                self.api_url_embed,
                headers=headers,
                json=json_data,
                proxies=self.proxy.proxies if self.proxy else None
            )
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to process request: {e}")
            raise