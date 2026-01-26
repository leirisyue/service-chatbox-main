** Update Data
/sync/{table_name}/update
{
  "data": {
    "id_sap": "100001000358_123",
    "material_name": "Vật liệu mới 100001000358",
    "material_subgroup":"chờ",
    "material_group":"vật liệu mới "
  }
}

** Insert Data
/sync/{table_name}/insert
{
  "data": [{
    "id_sap": "100001000358_yu",
    "material_name": "Vật liệu mới 100001000358",
    "material_subgroup":"chờ",
    "material_group":"vật liệu mới "
  }]
}

** Update Data By Keys
/sync/{table_name}/update/keys
{
  "list_key": [{"id_sap": "123"},{ "material_name":"Vật liệu A"}],
  "data": [
    {
    "id_sap": "123",
    "material_name": "Vật liệu mới 100001000358",
    "material_subgroup":"chờ",
    "material_group":"vật liệu mới "
  }]
}