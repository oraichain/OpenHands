import secrets

from eth_account import Account
from eth_account.messages import encode_defunct
from mnemonic import Mnemonic


def verify_ethereum_signature(message: str, signature: str) -> str:
    """
    Verify an Ethereum signature and return the signer's address
    """
    try:
        message_hash = encode_defunct(text=message)
        recovered_address = Account.recover_message(message_hash, signature=signature)
        return recovered_address.lower()
    except Exception as e:
        raise ValueError(f'Invalid signature: {str(e)}')


def generate_mnemonic() -> str:
    """
    Generate a new BIP39 mnemonic (seed phrase)
    """
    mnemo = Mnemonic('english')
    return mnemo.generate(strength=256)  # 24 words


def get_address_from_mnemonic(mnemonic: str) -> str:
    """
    Get Ethereum address from mnemonic
    """
    # Create seed from mnemonic
    Account.enable_unaudited_hdwallet_features()
    account = Account.from_mnemonic(mnemonic)
    return account.address.lower()


def generate_nonce() -> str:
    """
    Generate a random nonce for signing
    """
    return secrets.token_hex(32)
