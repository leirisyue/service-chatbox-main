
from typing import Any, Dict, List, Union
from pydantic import BaseModel

class UpsertRequest(BaseModel ):
    data: Union[Dict[str, Any], List[Dict[str, Any]]]
