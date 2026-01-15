import cv2
import numpy as np
from typing import Dict


def detect_face(image_bytes: bytes) -> Dict:
    """
    Detecta rostos na imagem usando Haar Cascade do OpenCV.

    Args:
        image_bytes: Bytes da imagem (JPEG, PNG, etc.)

    Returns:
        dict: {
            "face_detected": bool,  # Se pelo menos um rosto foi detectado
            "face_count": int       # Quantidade de rostos detectados
        }
    """
    try:
        # Converte bytes para array numpy
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return {"face_detected": False, "face_count": 0}

        # Converte para escala de cinza (necessário para Haar Cascade)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Carrega o classificador Haar Cascade para detecção facial
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )

        # Detecta rostos na imagem
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
            flags=cv2.CASCADE_SCALE_IMAGE
        )

        face_count = len(faces)

        return {
            "face_detected": face_count > 0,
            "face_count": face_count
        }

    except Exception as e:
        print(f"Erro na detecção facial: {e}")
        return {"face_detected": False, "face_count": 0}
