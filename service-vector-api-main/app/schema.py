
from typing import Any, Dict, List, Union
from pydantic import BaseModel


class UpsertRequest(BaseModel):
    data: Union[Dict[str, Any], List[Dict[str, Any]]]


class UpdateByKeysRequest(BaseModel):
    # list_key là list các object, ví dụ:
    # [ {"id_sap": 123}, {"material_name": "gỗ"} ]
    list_key: List[Dict[str, Any]]
    data: Union[Dict[str, Any], List[Dict[str, Any]]]
