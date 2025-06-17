import re, os
from yaml import load, FullLoader
from pathlib import Path
from web3 import Web3

pattern = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
def camel_to_snake(a_str):
    return pattern.sub('_', a_str).lower()

CONFIG_DIR = Path(os.getenv('S8_CONFIG_DIR', 'op_s8_vote_calc/config'))

def load_config():

    deployment = os.getenv('S8_DEPLOYMENT', 'test')

    with open(CONFIG_DIR / 'onchain_config.yaml', 'r') as f:
        onchain_config = load(f, Loader=FullLoader)[deployment]
    
    with open(CONFIG_DIR / 'offchain_config.yaml', 'r') as f:
        offchain_config = load(f, Loader=FullLoader)[deployment]

    return onchain_config, offchain_config

def get_web3():

    on_chain_config, _ = load_config()

    rpc = os.getenv('S8_JSON_RPC', on_chain_config['rpc'])
    
    if rpc is None:
        raise Exception("S8_JSON_RPC environment variable is not set")

    w3 = Web3(Web3.HTTPProvider(rpc))

    return w3
    
