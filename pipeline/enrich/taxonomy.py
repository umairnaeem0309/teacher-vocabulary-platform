"""Deterministic thematic taxonomy (Phase 9, sections 18, 50, 85).

A fixed, versioned hierarchy (``tax-v1``): 24 top-level categories with
subcategories (section 18's minimum set). Classification is deterministic
and low-cost (section 50): no LLM, three evidence sources in priority
order —

1. **headword** (0.90): the headword itself is a domain keyword
   (``airport`` -> travel/airports); highest precision;
2. **wordnet-chain** (0.85): the sense's Phase 8 synset link, or its
   hypernym ancestors (bounded walk), has a definition whose tokens
   include the category's domain token (``dog`` -> ... -> ``animal``
   -> nature);
3. **gloss** (0.60–0.80): category keyword stems present in the gloss
   (sub rule with >= 2 distinct hits 0.80, single hit 0.65, top-level
   keyword 0.70/0.60).

Multiple categories per sense are allowed (section 85). A subcategory hit
also assigns its parent top (retrieval filters by top or sub). Uncate-
gorized senses are normal and counted — categories are retrieval/filtering
aids, never a prerequisite for semantic search (sections 18, 85).
Version: ``tax-v1.2`` (audit: the headword tier now requires same-
category gloss corroboration — word-form evidence alone misassigned
polysemous keywords like fast/train/mark to every sense; v1.1 removed
single-keyword gloss hits as noise and pruned prone keywords; the
wnlink-v1.1 stemmer guard removed dose->do-style over-stems). Keyword
tables are data, changed only with a new version so historical
assignments stay explainable (§12, §127).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.enrich.wordnet import stem_token
from pipeline.identity.identity import _significant_tokens
from pipeline.normalize.clean import search_key

TAXONOMY_VERSION = "tax-v1.2"

# Confidence tiers (documented in D011; v1.1 audit reshaped the gloss
# tier — single-keyword gloss hits are noise and no longer assign).
_CONF_HEADWORD = 0.90
_CONF_WORDNET_CHAIN = 0.85
_CONF_GLOSS_SUB_MULTI = 0.80   # >= 2 distinct sub keywords in gloss
_CONF_GLOSS_TOP_MULTI = 0.70
_METHOD_ORDER = {"headword": 3, "wordnet-chain": 2, "gloss": 1}

# Hypernym walk is bounded to keep runs deterministic and cheap.
_CHAIN_DEPTH = 5


@dataclass(frozen=True)
class SubRule:
    """One subcategory: key, display name, gloss/headword keywords."""

    key: str
    name: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class TopRule:
    """One top-level category with subs, top-only keywords and WordNet
    ancestor domain tokens."""

    key: str
    name: str
    position: int
    subs: tuple[SubRule, ...]
    top_keywords: tuple[str, ...]
    domain_tokens: tuple[str, ...]


def _sub(key: str, name: str, *keywords: str) -> SubRule:
    return SubRule(key=key, name=name, keywords=tuple(keywords))


def _top(
    key: str,
    name: str,
    position: int,
    subs: tuple[SubRule, ...],
    top_keywords: tuple[str, ...] = (),
    domain_tokens: tuple[str, ...] = (),
) -> TopRule:
    return TopRule(
        key=key,
        name=name,
        position=position,
        subs=subs,
        top_keywords=tuple(top_keywords),
        domain_tokens=tuple(domain_tokens),
    )


TAXONOMY: tuple[TopRule, ...] = (
    _top(
        "travel", "Travel", 1,
        (
            _sub("travel-airports", "Airports",
                 "airport", "airfield", "runway", "terminal", "boarding", "security"),
            _sub("travel-flights", "Flights",
                 "layover", "turbulence", "departure", "arrival"),
            _sub("travel-hotels", "Hotels",
                 "hotel", "hostel", "motel", "reception", "checkin", "suite", "booking"),
            _sub("travel-reservations", "Reservations",
                 "reserve", "reservation", "book", "confirm", "cancel", "voucher"),
            _sub("travel-tourism", "Tourism",
                 "tourism", "tourist", "tour", "resort", "vacation", "guidebook"),
            _sub("travel-sightseeing", "Sightseeing",
                 "sightseeing", "landmark", "attraction", "museum", "monument", "excursion"),
            _sub("travel-documents", "Travel Documents",
                 "passport", "visa", "customs", "itinerary", "ticket", "luggage"),
            _sub("travel-problems", "Travel Problems",
                 "delay", "cancellation", "lost", "stolen", "complaint", "emergency"),
            _sub("travel-transport", "Public Transportation",
                 "bus", "metro", "subway", "tram", "shuttle", "fare", "timetable"),
        ),
        top_keywords=("travel", "trip", "journey", "voyage", "abroad", "aboard"),
        domain_tokens=(
            "travel", "tourism", "journey", "voyage", "trip",
            "accommodation", "lodging", "airfield",
        ),
    ),
    _top(
        "home-housing", "Home & Housing", 2,
        (
            _sub("home-rooms", "Rooms",
                 "room", "bedroom", "kitchen", "bathroom", "attic", "basement", "hallway"),
            _sub("home-furniture", "Furniture",
                 "furniture", "sofa", "wardrobe", "shelf", "table", "chair", "mattress"),
            _sub("home-appliances", "Appliances",
                 "appliance", "fridge", "oven", "dishwasher", "washing", "microwave", "kettle"),
            _sub("home-maintenance", "Maintenance",
                 "repair", "fix", "plumber", "leak", "renovate", "maintain", "tool"),
            _sub("home-materials", "Building Materials",
                 "brick", "concrete", "timber", "plaster", "cement", "tile"),
            _sub("home-renting", "Renting",
                 "rent", "tenant", "landlord", "lease", "deposit", "evict"),
            _sub("home-property", "Property",
                 "property", "mortgage", "estate", "ownership", "deed"),
            _sub("home-utilities", "Utilities",
                 "electricity", "heating", "sewage", "plumbing", "utility"),
            _sub("home-gardening", "Gardening",
                 "garden", "lawn", "mow", "plant", "flowerbed", "hedge", "rake"),
        ),
        top_keywords=("home", "house", "flat", "apartment", "housing"),
        domain_tokens=("house", "home", "dwelling", "residence", "building"),
    ),
    _top(
        "family-relationships", "Family & Relationships", 3,
        (
            _sub("family-members", "Family Members",
                 "mother", "father", "sister", "brother", "son", "daughter", "grandparent"),
            _sub("family-friendship", "Friendship",
                 "friend", "friendship", "acquaintance", "companion", "mate"),
            _sub("family-love", "Love & Marriage",
                 "love", "marriage", "wedding", "engaged", "divorce", "spouse", "partner"),
            _sub("family-children", "Children",
                 "child", "baby", "toddler", "teenager", "adolescent", "parenting"),
            _sub("family-relatives", "Relatives",
                 "relative", "cousin", "nephew", "niece", "aunt", "uncle", "inlaw"),
            _sub("family-events", "Social Events",
                 "party", "celebration", "gathering", "anniversary", "reunion"),
        ),
        top_keywords=("family", "relative", "relationship", "kin"),
        domain_tokens=("family", "kin", "relative", "parent", "child", "marriage", "relationship"),
    ),
    _top(
        "food-cooking", "Food & Cooking", 4,
        (
            _sub("food-ingredients", "Food & Ingredients",
                 "food", "ingredient", "meat", "vegetable", "fruit", "bread", "cheese", "rice"),
            _sub("food-methods", "Cooking Methods",
                 "cook", "bake", "boil", "fry", "grill", "roast", "steam", "simmer", "chop"),
            _sub("food-kitchen", "Kitchen & Utensils",
                 "kitchen", "pan", "pot", "knife", "spoon", "fork", "plate", "cutlery"),
            _sub("food-meals", "Meals",
                 "meal", "breakfast", "lunch", "dinner", "supper", "snack", "portion"),
            _sub("food-drinks", "Drinks",
                 "drink", "beverage", "coffee", "tea", "juice", "wine", "beer"),
            _sub("food-eating-out", "Eating Out",
                 "restaurant", "cafe", "menu", "waiter", "order", "tip", "canteen"),
            _sub("food-taste", "Taste & Flavour",
                 "taste", "flavour", "sweet", "sour", "bitter", "salty", "spicy", "delicious"),
            _sub("food-diets", "Diets",
                 "diet", "vegetarian", "vegan", "allergy", "gluten", "fasting"),
        ),
        top_keywords=("food", "meal", "cuisine", "recipe"),
        domain_tokens=("food", "cook", "culinary", "meal", "edible", "dish", "beverage"),
    ),
    _top(
        "work-business", "Work & Business", 5,
        (
            _sub("work-jobs", "Jobs & Professions",
                 "job", "profession", "worker", "employee", "employer", "staff", "colleague"),
            _sub("work-workplace", "Workplace",
                 "office", "workplace", "desk", "shift", "workshop", "factory"),
            _sub("work-meetings", "Meetings",
                 "meeting", "conference", "agenda", "deadline", "negotiation", "presentation"),
            _sub("work-communication", "Business Communication",
                 "email", "report", "memo", "correspondence", "enquiry", "quotation"),
            _sub("work-career", "Career",
                 "career", "promotion", "cv", "interview", "recruit", "resign", "retire"),
            _sub("work-companies", "Companies",
                 "company", "firm", "enterprise", "corporation", "startup", "client"),
            _sub("work-projects", "Projects",
                 "project", "plan", "task", "progress", "milestone", "deliver"),
        ),
        top_keywords=("work", "business", "job", "employment", "professional"),
        domain_tokens=(
        "business", "commerce", "employment", "occupation", "worker", "company", "corporation",),

    ),
    _top(
        "money-finance", "Money & Finance", 6,
        (
            _sub("money-payment", "Payment",
                 "pay", "payment", "cash", "card", "cheque", "installment", "refund"),
            _sub("money-banking", "Banking",
                 "bank", "account", "deposit", "withdraw", "loan", "mortgage", "interest"),
            _sub("money-prices", "Prices & Costs",
                 "price", "cost", "expensive", "cheap", "discount", "fee", "charge"),
            _sub("money-income", "Income & Salaries",
                 "salary", "wage", "income", "earn", "pension", "bonus", "profit"),
            _sub("money-debt", "Debt & Credit",
                 "debt", "credit", "borrow", "owe", "insolvent", "bankrupt"),
            _sub("money-investment", "Investment",
                 "invest", "stock", "share", "bond", "dividend", "savings"),
            _sub("money-currency", "Currency",
                 "currency", "money", "coin", "note", "exchange", "euro", "dollar", "zloty"),
        ),
        top_keywords=("money", "finance", "financial", "budget"),
        domain_tokens=("money", "finance", "payment", "monetary", "financial", "currency"),
    ),
    _top(
        "education", "Education", 7,
        (
            _sub("edu-school", "School & University",
                 "school", "university", "college", "campus", "kindergarten", "academy"),
            _sub("edu-subjects", "Subjects",
                 "subject", "math", "history", "biology", "chemistry", "geography", "physics"),
            _sub("edu-studying", "Studying",
                 "study", "learn", "revise", "practice", "homework", "memorize"),
            _sub("edu-exams", "Exams & Assessment",
                 "exam", "test", "quiz", "grade", "mark", "assessment", "certificate"),
            _sub("edu-people", "Teachers & Students",
                 "teacher", "student", "pupil", "professor", "tutor", "lecturer", "classmate"),
            _sub("edu-materials", "Materials",
                 "textbook", "notebook", "exercise", "dictionary", "blackboard", "stationery"),
        ),
        top_keywords=("education", "school", "academic", "lesson"),
        domain_tokens=("education", "school", "teaching", "learning", "academic", "university"),
    ),
    _top(
        "technology", "Technology", 8,
        (
            _sub("tech-computers", "Computers",
                 "computer", "laptop", "pc", "keyboard", "screen", "mouse", "hardware"),
            _sub("tech-software", "Software",
                 "software", "program", "application", "app", "update", "install", "bug"),
            _sub("tech-devices", "Devices",
                 "device", "phone", "smartphone", "tablet", "camera", "printer", "charger"),
            _sub("tech-networks", "Networks",
                 "network", "wifi", "router", "connection", "bandwidth", "server"),
            _sub("tech-programming", "Programming",
                 "code", "coding", "programming", "developer", "algorithm", "database"),
            _sub("tech-problems", "Technical Problems",
                 "crash", "freeze", "malfunction", "glitch", "broken", "virus"),
        ),
        top_keywords=("technology", "technical", "digital", "electronic"),
        domain_tokens=(
        "computer", "computing", "technology", "machine", "electronic", "digital", "software",),

    ),
    _top(
        "internet-social", "Internet & Social Media", 9,
        (
            _sub("web-browsing", "Websites & Browsing",
                 "website", "browser", "browse", "link", "page", "search", "download"),
            _sub("web-social", "Social Networks",
                 "social", "profile", "follower", "post", "like", "share", "influencer"),
            _sub("web-messaging", "Messaging",
                 "message", "chat", "text", "messenger", "whatsapp", "notification"),
            _sub("web-content", "Online Content",
                 "content", "video", "stream", "podcast", "vlog", "meme"),
            _sub("web-email", "Email",
                 "email", "inbox", "attach", "spam", "compose", "forward"),
            _sub("web-behaviour", "Online Behaviour",
                 "online", "privacy", "password", "troll", "harassment", "anonymous"),
        ),
        top_keywords=("internet", "online", "web", "website"),
        domain_tokens=("internet", "web", "online", "website", "network"),
    ),
    _top(
        "news-media", "News & Media", 10,
        (
            _sub("news-events", "News Events",
                 "news", "headline", "event", "breaking", "report", "story"),
            _sub("news-journalism", "Journalism",
                 "journalist", "journalism", "editor", "article", "press", "interview"),
            _sub("news-broadcast", "Broadcasting",
                 "broadcast", "channel", "television", "radio", "live", "episode"),
            _sub("news-print", "Print Media",
                 "newspaper", "magazine", "tabloid", "editorial", "column"),
            _sub("news-digital", "Digital Media",
                 "digital", "portal", "newsletter", "feed", "podcast"),
        ),
        top_keywords=("news", "media", "headline"),
        domain_tokens=("news", "media", "journalism", "press", "broadcast", "report"),
    ),
    _top(
        "entertainment", "Entertainment", 11,
        (
            _sub("ent-music", "Music",
                 "music", "song", "concert", "band", "singer", "album", "melody", "rhythm"),
            _sub("ent-cinema", "Cinema & Theatre",
                 "cinema", "film", "movie", "theatre", "actor", "performance", "scene"),
            _sub("ent-games", "Games",
                 "game", "puzzle", "board", "chess", "card", "console", "gaming"),
            _sub("ent-reading", "Books & Reading",
                 "book", "read", "novel", "author", "poem", "literature", "story"),
            _sub("ent-events", "Events & Parties",
                 "party", "celebrity", "premiere", "gala", "festival"),
        ),
        top_keywords=("entertainment", "fun", "leisure"),
        domain_tokens=("entertainment", "amusement", "recreation", "leisure", "fun"),
    ),
    _top(
        "health", "Health", 12,
        (
            _sub("health-body", "Body & Anatomy",
                 "body", "head", "heart", "lung", "blood", "bone", "muscle", "skin", "brain"),
            _sub("health-illness", "Illness & Symptoms",
                 "illness", "disease", "sick", "symptom", "fever", "cough", "pain", "injury"),
            _sub("health-treatment", "Treatment & Medicine",
                 "medicine", "treatment", "pill", "tablet", "vaccine",
                 "therapy", "surgery"),
            _sub("health-facilities", "Hospitals & Clinics",
                 "hospital", "clinic", "ward", "ambulance", "patient", "surgery"),
            _sub("health-lifestyle", "Healthy Lifestyle",
                 "healthy", "fitness", "nutrition", "exercise", "wellness", "hygiene"),
            _sub("health-mental", "Mental Health",
                 "mental", "anxiety", "depression", "stress", "therapy", "burnout"),
        ),
        top_keywords=("health", "healthy", "medical", "medicine"),
        domain_tokens=(
        "medicine", "medical", "disease", "illness", "therapy", "doctor", "anatomical",),

    ),
    _top(
        "shopping", "Shopping", 13,
        (
            _sub("shop-stores", "Stores & Markets",
                 "shop", "store", "market", "mall", "boutique", "supermarket", "aisle"),
            _sub("shop-buying", "Buying & Selling",
                 "buy", "sell", "purchase", "customer", "seller", "bargain", "receipt"),
            _sub("shop-clothes", "Clothing & Fashion",
                 "clothes", "clothing", "shirt", "trousers", "shoes", "fashion", "wear", "fitting"),
            _sub("shop-online", "Online Shopping",
                 "basket", "checkout", "delivery", "parcel", "courier", "order"),
            _sub("shop-groceries", "Groceries",
                 "grocery", "groceries", "dairy", "bakery", "butcher", "aisle"),
            _sub("shop-complaints", "Returns & Complaints",
                 "return", "refund", "complaint", "warranty", "faulty", "exchange"),
        ),
        top_keywords=("shopping", "shop", "store", "retail"),
        domain_tokens=("shop", "store", "purchase", "retail", "merchandise"),
    ),
    _top(
        "transportation", "Transportation", 14,
        (
            _sub("trans-road", "Road Traffic",
                 "road", "traffic", "highway", "junction", "crossing", "roundabout", "lane"),
            _sub("trans-vehicles", "Vehicles & Driving",
                 "car", "vehicle", "drive", "driver", "wheel", "brake", "engine", "petrol"),
            _sub("trans-public", "Public Transport",
                 "train", "tram", "bus", "underground", "platform", "commute"),
            _sub("trans-air-sea", "Air & Sea",
                 "plane", "ship", "ferry", "boat", "sail", "harbour", "port"),
            _sub("trans-directions", "Directions",
                 "direction", "left", "right", "straight", "map", "navigate", "distance"),
            _sub("trans-tickets", "Tickets & Fares",
                 "ticket", "fare", "single", "return", "season", "concession"),
            _sub("trans-problems", "Accidents & Breakdowns",
                 "accident", "crash", "breakdown", "collision", "tow", "puncture"),
        ),
        top_keywords=("transport", "transportation", "commute"),
        domain_tokens=("vehicle", "transport", "conveyance", "automobile", "aircraft", "boat"),
    ),
    _top(
        "nature", "Nature", 15,
        (
            _sub("nature-animals", "Animals",
                 "animal", "dog", "cat", "horse", "bird", "fish", "insect", "wildlife"),
            _sub("nature-plants", "Plants",
                 "plant", "tree", "flower", "grass", "leaf", "forest", "bush"),
            _sub("nature-landscape", "Landscape",
                 "mountain", "hill", "valley", "field", "meadow", "desert", "cliff"),
            _sub("nature-water", "Sea & Water",
                 "sea", "ocean", "river", "lake", "stream", "wave", "beach", "coast"),
            _sub("nature-space", "Space",
                 "space", "planet", "star", "moon", "sun", "galaxy", "orbit"),
            _sub("nature-ecology", "Environment & Ecology",
                 "environment", "ecology", "pollution", "recycle", "climate", "conservation"),
        ),
        top_keywords=("nature", "wild", "wildlife"),
        domain_tokens=("animal", "mammal", "bird", "plant", "tree", "flower", "insect", "fish"),
    ),
    _top(
        "weather", "Weather", 16,
        (
            _sub("weather-conditions", "Weather Conditions",
                 "rain", "snow", "wind", "fog", "cloud", "sunshine", "storm",
                 "drizzle", "thunder", "lightning", "breeze", "hail", "frost", "mist"),
            _sub("weather-seasons", "Seasons",
                 "season", "spring", "summer", "autumn", "winter"),
            _sub("weather-climate", "Climate",
                 "climate", "tropical", "arctic", "mediterranean", "continental"),
            _sub("weather-disasters", "Natural Disasters",
                 "flood", "drought", "hurricane", "tornado", "earthquake", "landslide"),
            _sub("weather-temperature", "Temperature",
                 "temperature", "hot", "cold", "warm", "freezing", "degrees"),
        ),
        top_keywords=("weather", "forecast"),
        domain_tokens=("weather", "atmospheric", "precipitation", "wind", "storm", "climate"),
    ),
    _top(
        "society", "Society", 17,
        (
            _sub("soc-issues", "Social Issues",
                 "poverty", "inequality", "unemployment", "homeless", "discrimination"),
            _sub("soc-community", "Community",
                 "community", "neighbour", "neighbourhood", "association", "local"),
            _sub("soc-law", "Law & Crime",
                 "law", "crime", "police", "court", "theft", "prison", "guilty", "trial"),
            _sub("soc-culture", "Customs & Culture",
                 "culture", "custom", "tradition", "festival", "heritage"),
            _sub("soc-volunteering", "Charity & Volunteering",
                 "charity", "volunteer", "donate", "fundraising", "aid"),
        ),
        top_keywords=("society", "social", "community"),
        domain_tokens=("society", "social", "community", "culture", "custom"),
    ),
    _top(
        "government", "Government", 18,
        (
            _sub("gov-politics", "Politics",
                 "politics", "political", "democracy", "ideology", "policy", "minister"),
            _sub("gov-admin", "Public Administration",
                 "administration", "bureaucracy", "office", "department", "official"),
            _sub("gov-citizenship", "Citizenship & Immigration",
                 "citizen", "immigration", "emigrate", "border", "asylum", "residence"),
            _sub("gov-elections", "Elections",
                 "election", "vote", "voter", "candidate", "ballot", "campaign", "parliament"),
            _sub("gov-services", "Public Services",
                 "service", "tax", "benefit", "registry", "council"),
            _sub("gov-laws", "Laws & Regulations",
                 "regulation", "legislation", "act", "statute", "compliance"),
        ),
        top_keywords=("government", "state", "public"),
        domain_tokens=("government", "political", "politics", "authority", "administration"),
    ),
    _top(
        "communication", "Communication", 19,
        (
            _sub("comm-speaking", "Speaking & Conversation",
                 "speak", "conversation", "discuss", "chat", "greet", "introduce"),
            _sub("comm-writing", "Writing & Texts",
                 "write", "text", "essay", "letter", "note", "draft", "handwriting"),
            _sub("comm-language", "Language & Grammar",
                 "language", "grammar", "word", "meaning", "translate", "vocabulary", "pronounce"),
            _sub("comm-requests", "Requests & Suggestions",
                 "request", "suggest", "recommend", "propose", "invite", "offer"),
            _sub("comm-opinions", "Opinions & Agreement",
                 "opinion", "agree", "disagree", "argue", "persuade", "debate"),
            _sub("comm-telephone", "Telephone",
                 "phone", "call", "ring", "voicemail", "dial", "hang"),
        ),
        top_keywords=("communication", "communicate"),
        domain_tokens=("communicate", "communication", "speech", "language", "conversation"),
    ),
    _top(
        "emotions", "Emotions", 20,
        (
            _sub("emo-joy", "Happiness & Sadness",
                 "happy", "happiness", "joy", "sad", "sadness", "cheerful", "miserable"),
            _sub("emo-fear-anger", "Fear & Anger",
                 "fear", "afraid", "angry", "anger", "rage", "frightened", "annoyed"),
            _sub("emo-surprise", "Surprise & Disgust",
                 "surprise", "surprised", "shocked", "disgust", "astonished"),
            _sub("emo-states", "Emotional States",
                 "emotion", "feeling", "mood", "excited", "bored", "nervous", "calm"),
            _sub("emo-support", "Empathy & Support",
                 "empathy", "sympathy", "comfort", "console", "support", "understanding"),
        ),
        top_keywords=("emotion", "feel", "feeling", "mood"),
        domain_tokens=(
        "emotion", "feeling", "emotional", "affection", "fear", "anger", "happiness",),

    ),
    _top(
        "personality", "Personality", 21,
        (
            _sub("per-traits", "Character Traits",
                 "personality", "character", "trait", "temperament", "disposition"),
            _sub("per-positive", "Positive Qualities",
                 "kind", "honest", "generous", "brave", "patient", "reliable", "cheerful"),
            _sub("per-negative", "Negative Qualities",
                 "selfish", "greedy", "lazy", "rude", "cruel", "arrogant", "stubborn"),
            _sub("per-attitudes", "Attitudes & Behaviour",
                 "attitude", "behaviour", "manner", "confident", "shy", "polite"),
            _sub("per-roles", "Identities & Roles",
                 "leader", "hero", "coward", "genius", "beginner", "expert"),
        ),
        top_keywords=("personality", "character"),
        domain_tokens=("personality", "character", "trait", "temperament", "disposition"),
    ),
    _top(
        "sports", "Sports", 22,
        (
            _sub("sport-disciplines", "Sports & Disciplines",
                 "football", "basketball", "tennis", "swimming", "cycling",
                 "boxing", "skiing"),
            _sub("sport-competition", "Competition",
                 "match", "tournament", "league", "championship", "opponent", "referee"),
            _sub("sport-equipment", "Equipment & Venues",
                 "stadium", "pitch", "court", "gym", "rink", "equipment", "kit"),
            _sub("sport-fitness", "Fitness & Exercise",
                 "fitness", "workout", "training", "stretch", "jog", "exercise"),
            _sub("sport-results", "Results & Winning",
                 "win", "lose", "victory", "defeat", "medal", "champion"),
        ),
        top_keywords=("sport", "sports", "athletic"),
        domain_tokens=("sport", "athletic", "contest", "game", "gymnastic", "play"),
    ),
    _top(
        "hobbies", "Hobbies", 23,
        (
            _sub("hob-games", "Games & Play",
                 "hobby", "pastime", "play", "collect", "collection", "quiz"),
            _sub("hob-crafts", "Arts & Crafts",
                 "craft", "draw", "paint", "knit", "sew", "pottery", "carve"),
            _sub("hob-music", "Music Making",
                 "instrument", "guitar", "piano", "violin", "drum", "practise"),
            _sub("hob-photography", "Photography",
                 "photo", "photography", "camera", "lens", "selfie", "album"),
            _sub("hob-leisure", "Leisure & Free Time",
                 "free", "spare", "relax", "unwind", "weekend"),
        ),
        top_keywords=("hobby", "pastime"),
        domain_tokens=("hobby", "pastime", "recreation", "leisure", "amusement"),
    ),
    _top(
        "daily-life", "Daily Life", 24,
        (
            _sub("daily-routines", "Daily Routines",
                 "routine", "habit", "everyday", "usual"),
            _sub("daily-housework", "Housework",
                 "chore", "clean", "tidy", "vacuum", "laundry", "iron", "wash", "dust"),
            _sub("daily-errands", "Errands",
                 "errand", "post", "queue", "collect", "deliver", "appointment"),
            _sub("daily-celebrations", "Celebrations & Holidays",
                 "holiday", "birthday", "christmas", "easter", "gift", "present", "celebrate"),
            _sub("daily-rest", "Sleep & Rest",
                 "sleep", "nap", "rest", "tired", "relax", "bedtime", "dream"),
        ),
        top_keywords=("daily", "everyday", "routine"),
        domain_tokens=("routine", "daily", "everyday", "habit"),
    ),
)

assert len(TAXONOMY) == 24


def _stem_set(words: tuple[str, ...]) -> frozenset[str]:
    return frozenset(stem_token(search_key(w)) for w in words if w)


@dataclass(frozen=True)
class _CompiledTop:
    rule: TopRule
    sub_stems: tuple[tuple[SubRule, frozenset[str]], ...]
    top_stems: frozenset[str]
    domain_stems: frozenset[str]


def _compile_taxonomy() -> tuple[_CompiledTop, ...]:
    compiled = []
    for rule in TAXONOMY:
        compiled.append(
            _CompiledTop(
                rule=rule,
                sub_stems=tuple((s, _stem_set(s.keywords)) for s in rule.subs),
                top_stems=_stem_set(rule.top_keywords),
                domain_stems=_stem_set(rule.domain_tokens),
            )
        )
    return tuple(compiled)


_COMPILED: tuple[_CompiledTop, ...] = _compile_taxonomy()


@dataclass
class CategoryAssignment:
    """One category (or subcategory) assigned to a sense."""

    category_key: str      # top key, e.g. "travel"
    subcategory_key: str | None  # sub key, e.g. "travel-airports"
    confidence: float
    method: str            # headword | wordnet-chain | gloss
    version: str = TAXONOMY_VERSION


@dataclass
class TaxonomyReport:
    """QC counters for the classification pass (§126)."""

    senses_total: int = 0
    senses_categorized: int = 0
    uncategorized: int = 0
    assignments_created: int = 0
    multi_category_senses: int = 0
    by_category: dict = field(default_factory=dict)
    version: str = TAXONOMY_VERSION

    def as_dict(self) -> dict:
        return {
            "senses_total": self.senses_total,
            "senses_categorized": self.senses_categorized,
            "uncategorized": self.uncategorized,
            "assignments_created": self.assignments_created,
            "multi_category_senses": self.multi_category_senses,
            "by_category": dict(sorted(self.by_category.items())),
            "version": self.version,
        }


def taxonomy_nodes() -> list[dict]:
    """Flatten the hierarchy to node rows (key, name, parent_key, position)."""
    rows = []
    for top in TAXONOMY:
        rows.append(
            {"key": top.key, "name": top.name, "parent_key": None,
             "position": top.position}
        )
        for pos, sub in enumerate(top.subs, start=1):
            rows.append(
                {"key": sub.key, "name": sub.name, "parent_key": top.key,
                 "position": pos}
            )
    return rows


def _hypernym_adjacency(catalog: Any) -> dict[str, list[str]]:
    """synset id -> direct hypernym targets (deduped, deterministic)."""
    adj: dict[str, list[str]] = {}
    if catalog is None:
        return adj
    for rel in catalog.relations:
        if rel.relation == "hypernym":
            targets = adj.setdefault(rel.from_synset_id, [])
            if rel.to_synset_id not in targets:
                targets.append(rel.to_synset_id)
    return adj


def _chain_definition_stems(
    start_id: str,
    catalog: Any,
    adj: dict[str, list[str]],
) -> frozenset[str]:
    """Definition stems of the synset and its hypernym ancestors (bounded)."""
    stems: set[str] = set()
    seen: set[str] = set()
    frontier = [start_id]
    for _depth in range(_CHAIN_DEPTH + 1):
        next_frontier: list[str] = []
        for synset_id in frontier:
            if synset_id in seen:
                continue
            seen.add(synset_id)
            entry = catalog.synsets.get(synset_id)
            if entry is not None:
                stems.update(entry.definition_stems)
            next_frontier.extend(adj.get(synset_id, []))
        frontier = next_frontier
        if not frontier:
            break
    return frozenset(stems)


def classify_senses(
    senses: list,
    links: dict[str, list] | None = None,
    catalog: Any = None,
) -> tuple[dict[str, list[CategoryAssignment]], TaxonomyReport]:
    """Classify every sense deterministically; returns assignments + QC.

    ``links`` maps sense_key -> [SenseWordnetLink] (Phase 8 output);
    ``catalog`` is the Phase 8 SynsetCatalog used for hypernym walks.
    """
    report = TaxonomyReport()
    adj = _hypernym_adjacency(catalog) if catalog else {}
    chain_cache: dict[str, frozenset[str]] = {}
    out: dict[str, list[CategoryAssignment]] = {}

    for sense in senses:
        report.senses_total += 1
        assignments = _classify_one(
            sense,
            (links or {}).get(sense.sense_key),
            catalog,
            adj,
            chain_cache,
        )
        if assignments:
            out[sense.sense_key] = assignments
            report.senses_categorized += 1
            report.assignments_created += len(assignments)
            if len({a.category_key for a in assignments}) > 1:
                report.multi_category_senses += 1
            for a in assignments:
                report.by_category[a.category_key] = (
                    report.by_category.get(a.category_key, 0) + 1
                )
        else:
            report.uncategorized += 1

    return out, report


def _classify_one(
    sense: Any,
    sense_links: list | None,
    catalog: Any,
    adj: dict[str, list[str]],
    chain_cache: dict[str, frozenset[str]],
) -> list[CategoryAssignment]:
    """Deterministic per-sense classification (evidence order fixes tier)."""
    gloss_stems = {stem_token(t) for t in _significant_tokens(sense.gloss_search)}
    headword_stem = stem_token(search_key(sense.headword_search))

    # (category_key, subcategory_key) -> best assignment so far, by
    # (confidence, method order) — top and sub rows are distinct outputs.
    best: dict[tuple[str, str], CategoryAssignment] = {}

    def offer(candidate: CategoryAssignment) -> None:
        key = (candidate.category_key, candidate.subcategory_key or "")
        current = best.get(key)
        if current is None or (
            candidate.confidence,
            _METHOD_ORDER.get(candidate.method, 0),
        ) > (current.confidence, _METHOD_ORDER.get(current.method, 0)):
            best[key] = candidate

    # 1. Headword keyword, corroborated by gloss evidence (v1.2 audit
    # fix): a keyword headword alone is word-level evidence — it must
    # agree with same-category meaning evidence in the sense's gloss,
    # otherwise every sense of a polysemous keyword gets misassigned
    # ('fast' light-sensitive -> food-diets). The headword's own stem is
    # excluded from corroboration: glosses frequently repeat the headword
    # and self-corroboration is circular ('bank' aircraft sense).
    evidence_stems = gloss_stems - {headword_stem}
    for compiled in _COMPILED:
        category_stems = compiled.top_stems | compiled.domain_stems
        corroborated = bool(evidence_stems & category_stems)
        if headword_stem in compiled.top_stems and corroborated:
            offer(CategoryAssignment(
                category_key=compiled.rule.key, subcategory_key=None,
                confidence=_CONF_HEADWORD, method="headword",
            ))
        for sub, stems in compiled.sub_stems:
            if headword_stem in stems:
                sub_corroborated = bool(
                    evidence_stems & (stems | category_stems)
                )
                if sub_corroborated:
                    offer(CategoryAssignment(
                        category_key=compiled.rule.key, subcategory_key=sub.key,
                        confidence=_CONF_HEADWORD, method="headword",
                    ))
                    # Sub hit assigns the parent top too (retrieval by top).
                    offer(CategoryAssignment(
                        category_key=compiled.rule.key, subcategory_key=None,
                        confidence=_CONF_HEADWORD, method="headword",
                    ))

    # 2. WordNet hypernym-chain domain tokens (needs Phase 8 artifacts).
    if catalog is not None and sense_links:
        for link in sense_links:
            cached = chain_cache.get(link.synset_id)
            if cached is None:
                cached = _chain_definition_stems(link.synset_id, catalog, adj)
                chain_cache[link.synset_id] = cached
            stems = cached
            for compiled in _COMPILED:
                if compiled.domain_stems & stems:
                    offer(CategoryAssignment(
                        category_key=compiled.rule.key, subcategory_key=None,
                        confidence=_CONF_WORDNET_CHAIN, method="wordnet-chain",
                    ))

    # 3. Gloss keyword hits (v1.1: multi-keyword only — audit D011
    # showed single-keyword gloss hits are predominantly noise).
    for compiled in _COMPILED:
        for sub, stems in compiled.sub_stems:
            hits = len(evidence_stems & stems)
            if hits >= 2:
                offer(CategoryAssignment(
                    category_key=compiled.rule.key, subcategory_key=sub.key,
                    confidence=_CONF_GLOSS_SUB_MULTI, method="gloss",
                ))
                offer(CategoryAssignment(
                    category_key=compiled.rule.key, subcategory_key=None,
                    confidence=_CONF_GLOSS_SUB_MULTI, method="gloss",
                ))
        top_hits = len(evidence_stems & compiled.top_stems)
        if top_hits >= 2:
            offer(CategoryAssignment(
                category_key=compiled.rule.key, subcategory_key=None,
                confidence=_CONF_GLOSS_TOP_MULTI, method="gloss",
            ))

    return sorted(
        best.values(),
        key=lambda a: (a.category_key, a.subcategory_key or ""),
    )
