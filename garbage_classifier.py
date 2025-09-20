import os
from transformers import ViTForImageClassification, ViTImageProcessor
from PIL import Image
import torch
from dotenv import load_dotenv
load_dotenv()

model_name = "yangy50/garbage-classification"

HUGGING_FACE_TOKEN = os.getenv("HUGGING_FACE_TOKEN")


# Load the model and processor
processor = ViTImageProcessor.from_pretrained(model_name, use_auth_token=HUGGING_FACE_TOKEN)
model = ViTForImageClassification.from_pretrained(model_name, use_auth_token=HUGGING_FACE_TOKEN)

def classify_image(image_path):
    """
    Classifies an image from the given path.
    """
    try:
        # Open the image
        image = Image.open(image_path)
        return process_image(image)

    except Exception as e:
        return {"error": str(e)}

def classify_image_from_stream(image_stream):
    """
    Classifies an image from an in-memory stream.
    """
    try:
        # Open the image from the stream
        image = Image.open(image_stream)
        return process_image(image)

    except Exception as e:
        return {"error": str(e)}

def process_image(image: Image.Image):
    """
    Preprocesses an image and returns the classification result.
    """
    # Preprocess the image
    inputs = processor(images=image, return_tensors="pt")

    # Make a prediction
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits

    # Get the predicted class
    predicted_class_idx = logits.argmax(-1).item()
    predicted_class = model.config.id2label[predicted_class_idx]

    return {"predicted_class": predicted_class}

