class Proxy:
    def __init__(self, proxy_url):
        self.proxies = {
            'http': proxy_url,
            'https': proxy_url
        }