from database import get_db
from models import Intent
from ml_intent import IntentClassifier

db = next(get_db())

texts = []
labels = []

intents = db.query(Intent).all()

for intent in intents:
    for kw in intent.keywords.split(","):
        texts.append(kw.strip().lower())
        labels.append(intent.intent_type)

classifier = IntentClassifier()
classifier.train(texts, labels)

print("✅ ML model trained successfully")
