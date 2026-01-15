import math
from typing import Tuple


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcula a distância em metros entre duas coordenadas GPS usando a fórmula de Haversine.

    Args:
        lat1: Latitude do ponto 1
        lon1: Longitude do ponto 1
        lat2: Latitude do ponto 2
        lon2: Longitude do ponto 2

    Returns:
        Distância em metros
    """
    R = 6371000  # Raio da Terra em metros

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = math.sin(delta_lat / 2) ** 2 + \
        math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def is_within_radius(
    user_lat: float,
    user_lon: float,
    company_lat: float,
    company_lon: float,
    allowed_radius: float
) -> Tuple[bool, float]:
    """
    Verifica se o usuário está dentro do raio permitido da empresa.

    Args:
        user_lat: Latitude do usuário
        user_lon: Longitude do usuário
        company_lat: Latitude da empresa
        company_lon: Longitude da empresa
        allowed_radius: Raio permitido em metros

    Returns:
        Tupla (está_dentro, distância_em_metros)
    """
    distance = calculate_distance(user_lat, user_lon, company_lat, company_lon)
    return distance <= allowed_radius, distance
