
from eth_abi import decode
import json

class AttestionMeta:
    def __init__(self, schema_id, **kwtypes):
        self.schema_id = schema_id
        self.kwtypes = kwtypes
    
    @property
    def name(self):
        return self.__class__.__name__
    
    def decode(self, data):
        types = list(self.kwtypes.values())
        encoded = bytes.fromhex(data.replace("0x", ""))
        result = decode(types, encoded)
        result = {k: v for k, v in zip(self.kwtypes.keys(), result)}

        def bytes_to_str(x):
            if isinstance(x, bytes):
                return x.hex()
            return x

        result = {k : bytes_to_str(v) for k, v in result.items()}

        return result

bytes32 = bytes

class Citizens(AttestionMeta):
    def __init__(self, schema_id):
        super().__init__(schema_id, FarcaserId="uint256", SelectionMethod="string")

class CitizenWalletChange(AttestionMeta):
    def __init__(self, schema_id):
        super().__init__(schema_id, oldCitizenUID="bytes32")

class Vote(AttestionMeta):
    def __init__(self, schema_id):
        super().__init__(schema_id, proposalId="uint256", params="string")
    
    def decode(self, data):
        result = super().decode(data)
        result['params'] =  [int(x) for x in json.loads(result['params'])]
        return result

class CreateProposal(AttestionMeta):
    def __init__(self, schema_id):
        super().__init__(schema_id, contract='address', proposalId='uint256', proposer='address', description='string', choices='string[]', proposal_type_id='uint8', start_block='uint256', end_block='uint256', proposal_type='string', tiers='uint256[]', onchain_proposalid='uint256', max_approvals='uint8', criteria='uint8', criteria_value='uint128', calculation_options='uint8')


meta = {}

meta['test'] = {
    'citizen': Citizens('0x754160df7a4bd6ecf7e8801d54831a5d33403b4d52400e87d7611ee0eee6de23'),
    'citizen_wallet_change': CitizenWalletChange('0x3acfc8404d72c7112ef6f957f0fcf0a5c3e026b586c101ea25355d4666a00362'),
    'vote': Vote('0xec3674d93b7007e918cf91ddd44bd14f28d138a4e7f3a79214dc35da2aed794e'),
    'create_proposal': CreateProposal('0x590765de6f34bbae3e51aa89e571f567fa6d63cf3f8225592d58133860a0ccda')
}

meta['main'] = {
    'citizen': Citizens('0xc35634c4ca8a54dce0a2af61a9a9a5a3067398cb3916b133238c4f6ba721bc8a'),
    'citizen_wallet_change': CitizenWalletChange('0xa55599e411f0eb310d47357e7d6064b09023e1d6f8bcb5504c051572a37db5f7'),
    'vote': Vote('0xc113116804c90320b3d059ff8eed8b7171e3475f404f65828bbbe260dce15a99'),
    'create_proposal': CreateProposal('0xfc5b3c0472d09ac39f0cb9055869e70c4c59413041e3fd317f357789389971e4')
}