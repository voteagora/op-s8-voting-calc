
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
        super().__init__(schema_id, contract='address', id='uint256', proposer='address', description='string', choices='string[]', proposal_type_id='uint8', start_block='uint256', end_block='uint256', proposal_type='string', tiers='uint256[]', onchain_proposalid='uint256')


meta = {}

meta['test'] = {
    'citizen': Citizens('0x754160df7a4bd6ecf7e8801d54831a5d33403b4d52400e87d7611ee0eee6de23'),
    'citizen_wallet_change': CitizenWalletChange('0x3acfc8404d72c7112ef6f957f0fcf0a5c3e026b586c101ea25355d4666a00362'),
    'vote': Vote('0xe55f129f30d55bd712c8355141474f886a9d38f218d94b0d63a00e73c6d65a09'),
    # 'create_proposal': CreateProposal('0xc2d307e00cc97b07606361c49971814ed50e20b080a0fb7a3c9c94c224463539')
    # 'create_proposal': CreateProposal('0x875845d42b7cb72da8d97c3442182b9a0ee302d4a8d661ee8b83f13bf1f8f38b')
    'create_proposal': CreateProposal('0x590765de6f34bbae3e51aa89e571f567fa6d63cf3f8225592d58133860a0ccda') # Adds calculationOptions
}

meta['main'] = {
    'citizen': Citizens('0xc35634c4ca8a54dce0a2af61a9a9a5a3067398cb3916b133238c4f6ba721bc8a'),
    'citizen_wallet_change': CitizenWalletChange('TODO'),
    'vote': Vote('TODO'),
    'create_proposal': CreateProposal('TODO')
}