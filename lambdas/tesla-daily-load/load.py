import teslapy
import boto3
import json
import time

WAKE_WAIT_SECONDS = 30              # Time to wait after wake-up

def load_token():
    ssm = boto3.client('ssm')
    param = ssm.get_parameter(Name='/tesla/tokens', WithDecryption=True)
    return json.loads(param['Parameter']['Value'])

def save_token(token_dict):
    ssm = boto3.client('ssm')
    ssm.put_parameter(
        Name='/tesla/tokens',
        Value=json.dumps(token_dict),
        Type='SecureString',
        Overwrite=True
    )

def lambda_handler(event, context):
    tokens = load_token()
    def cache_loader():
        return tokens
    def cache_dumper(cache):
        save_token(cache)
    with teslapy.Tesla('your_email', cache_loader=cache_loader, cache_dumper=cache_dumper) as tesla:
        if not tesla.authorized:
            tesla.refresh_token(refresh_token=tokens['refresh_token'])
        vehicles = tesla.vehicle_list()
        if not vehicles:
            print("No vehicles found.")
            return
        vehicle = vehicles[0]  # Use the first vehicle

        # Check vehicle state
        state = vehicle['state']
        print(f"Initial vehicle state: {state}")

        if state == 'asleep':
            print("Vehicle is asleep, waking up...")
            vehicle.sync_wake_up()  # Wake up the car
            print(f"Waiting {WAKE_WAIT_SECONDS} seconds for vehicle to wake up...")
            time.sleep(WAKE_WAIT_SECONDS)
            vehicle = tesla.vehicle_list()[0]  # Refresh vehicle object
            print(f"Vehicle state after wake: {vehicle['state']}")

        # Try to get vehicle data
        data = vehicle.get_vehicle_data()
        print("Vehicle data:", data)


# Example local test (comment out for Lambda deployment)
# if __name__ == '__main__':
#     lambda_handler({}, {})
