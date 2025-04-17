import argparse
from igpt_apiClient import IgptAPIClient

def main():
    parser = argparse.ArgumentParser(description='IgptAPIClient CLI')
    parser.add_argument('--client_id', required=True, help='Client ID')
    parser.add_argument('--client_secret', required=True, help='Client Secret')
    args = parser.parse_args()

    client = IgptAPIClient(args.client_id, args.client_secret)

    # Example JSON data for the request
    json_data = {
        "input": "What is your name!"
    }

    # Process request
    try:
        response = client.process_request(json_data)
        print(response.json())
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()