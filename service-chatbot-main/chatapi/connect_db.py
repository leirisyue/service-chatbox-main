import psycopg2
from config import settings


def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

def get_db_origin():
    return psycopg2.connect(**settings.DB_CONFIG_ORIGIN)