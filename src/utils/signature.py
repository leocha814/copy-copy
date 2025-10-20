import hashlib
import jwt
import uuid
from urllib.parse import urlencode, unquote
from typing import Dict, Any, Optional

def generate_jwt_token(access_key: str, secret_key: str, query_params: Optional[Dict[str, Any]] = None) -> str:
    payload = {
        'access_key': access_key,
        'nonce': str(uuid.uuid4()),
    }
    
    if query_params:
        query_string = unquote(urlencode(query_params, doseq=True)).encode("utf-8")
        m = hashlib.sha512()
        m.update(query_string)
        query_hash = m.hexdigest()
        
        payload['query_hash'] = query_hash
        payload['query_hash_alg'] = 'SHA512'
    
    jwt_token = jwt.encode(payload, secret_key, algorithm='HS256')
    return f'Bearer {jwt_token}'