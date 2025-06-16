import re, os
from yaml import load, FullLoader
from pathlib import Path

pattern = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
def camel_to_snake(a_str):
    return pattern.sub('_', a_str).lower()

CONFIG_DIR = Path(os.getenv('S8_CONFIG_DIR', 'op_s8_vote_calc/config'))

def load_config(env):

    with open(CONFIG_DIR / 'onchain_config.yaml', 'r') as f:
        onchain_config = load(f, Loader=FullLoader)[env]
    
    with open(CONFIG_DIR / 'offchain_config.yaml', 'r') as f:
        offchain_config = load(f, Loader=FullLoader)[env]

    return onchain_config, offchain_config