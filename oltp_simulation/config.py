import os
from dotenv import load_dotenv

load_dotenv()


def _build_conn_string():
    driver = os.getenv("MSSQL_DRIVER", "ODBC Driver 17 for SQL Server")
    host = os.getenv("MSSQL_HOST", "localhost")
    port = os.getenv("MSSQL_PORT", "")
    instance = os.getenv("MSSQL_INSTANCE", "")
    database = os.getenv("MSSQL_DATABASE", "DarkStoreInventory")
    auth_type = os.getenv("MSSQL_AUTH_TYPE", "sql").lower()

    if instance:
        server = f"{host}\\{instance}"
    elif port:
        server = f"{host},{port}"
    else:
        server = host

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
    ]

    if auth_type == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        user = os.getenv("MSSQL_USERNAME", "sa")
        password = os.getenv("MSSQL_PASSWORD", "StrongPass123!")
        parts.append(f"UID={user}")
        parts.append(f"PWD={password}")

    trust_cert = os.getenv("MSSQL_TRUST_CERT", "yes").lower()
    if trust_cert == "yes":
        parts.append("TrustServerCertificate=yes")

    return ";".join(parts)


DB_CONN_STRING = _build_conn_string()

N_CUSTOMERS_SEED = 50
N_ORDERS_DEFAULT = 500

SIM_START_HOUR = 8
SIM_END_HOUR = 22
TICK_MIN_MINUTES = 2
TICK_MAX_MINUTES = 10

P_ORDER_CREATE = 0.50
P_ADVANCE_ORDER = 0.25
P_CUSTOMER_REG = 0.10
P_STOCK_ADJUST = 0.05
P_RESTOCK_CHECK = 0.10

P_CONFIRM = 0.85
P_DELIVER = 0.95

CONFIRM_DELAY_MIN = 2
CONFIRM_DELAY_MAX = 15
DELIVER_DELAY_MIN = 15
DELIVER_DELAY_MAX = 45

PAYMENT_METHODS = ["card", "cash", "wallet"]
PAYMENT_WEIGHTS = [0.45, 0.30, 0.25]

ORDER_ITEM_COUNT_WEIGHTS = [0.20, 0.30, 0.25, 0.15, 0.10]

SEED_DATE = "2025-01-01"

CATALOG = {
    "Dairy": {
        "requires_cold_chain": True,
        "price_range": (10, 60),
        "products": [
            ("Whole Milk 1L", "DAIRY-001", 7),
            ("Greek Yogurt 500g", "DAIRY-002", 14),
            ("Cheddar Cheese 200g", "DAIRY-003", 30),
            ("Mozzarella Ball 125g", "DAIRY-004", 21),
            ("Heavy Cream 500ml", "DAIRY-005", 10),
            ("Sour Cream 200ml", "DAIRY-006", 14),
            ("Labneh 500g", "DAIRY-007", 10),
            ("Butter 200g", "DAIRY-008", 60),
            ("Cream Cheese 150g", "DAIRY-009", 21),
            ("Flavored Yogurt Drink 330ml", "DAIRY-010", 10),
        ],
    },
    "Bakery": {
        "requires_cold_chain": False,
        "price_range": (5, 40),
        "products": [
            ("White Bread Loaf", "BAKE-001", 5),
            ("Whole Wheat Bread", "BAKE-002", 5),
            ("Croissant Plain", "BAKE-003", 3),
            ("Chocolate Croissant", "BAKE-004", 3),
            ("Bagels Pack 4", "BAKE-005", 5),
            ("Pita Bread Pack 5", "BAKE-006", 4),
            ("Brioche Burger Buns 4pk", "BAKE-007", 5),
            ("Sourdough Loaf", "BAKE-008", 4),
            ("Muffin Blueberry", "BAKE-009", 3),
            ("Danish Pastry", "BAKE-010", 3),
        ],
    },
    "Beverages": {
        "requires_cold_chain": False,
        "price_range": (8, 50),
        "products": [
            ("Coca-Cola 330ml", "BEV-001", 365),
            ("Pepsi 330ml", "BEV-002", 365),
            ("Sprite 330ml", "BEV-003", 365),
            ("Fresh Orange Juice 1L", "BEV-004", 7),
            ("Bottled Water 1.5L", "BEV-005", 730),
            ("Energy Drink 250ml", "BEV-006", 180),
            ("Iced Tea Lemon 500ml", "BEV-007", 30),
            ("Sparkling Water 1L", "BEV-008", 365),
            ("Mango Juice 1L", "BEV-009", 14),
            ("Cold Brew Coffee 250ml", "BEV-010", 14),
        ],
    },
    "Snacks": {
        "requires_cold_chain": False,
        "price_range": (5, 35),
        "products": [
            ("Potato Chips Classic 150g", "SNCK-001", 90),
            ("Tortilla Chips 200g", "SNCK-002", 60),
            ("Salted Peanuts 100g", "SNCK-003", 120),
            ("Trail Mix 150g", "SNCK-004", 90),
            ("Chocolate Bar 100g", "SNCK-005", 180),
            ("Biscuits Digestive 200g", "SNCK-006", 120),
            ("Popcorn Microwave 3pk", "SNCK-007", 180),
            ("Rice Cakes 100g", "SNCK-008", 60),
            ("Granola Bar Box 6", "SNCK-009", 120),
            ("Crackers 200g", "SNCK-010", 90),
        ],
    },
    "Frozen": {
        "requires_cold_chain": True,
        "price_range": (15, 80),
        "products": [
            ("Frozen Pizza Margherita", "FRZN-001", 90),
            ("Frozen French Fries 1kg", "FRZN-002", 180),
            ("Vanilla Ice Cream 1L", "FRZN-003", 180),
            ("Frozen Chicken Nuggets 500g", "FRZN-004", 120),
            ("Frozen Mixed Vegetables 500g", "FRZN-005", 180),
            ("Frozen Fish Fillets 400g", "FRZN-006", 90),
            ("Frozen Burger Patties 6pk", "FRZN-007", 90),
            ("Frozen Berries Mix 400g", "FRZN-008", 180),
            ("Frozen Spring Rolls 10pk", "FRZN-009", 120),
            ("Frozen Waffles 6pk", "FRZN-010", 60),
        ],
    },
    "Produce": {
        "requires_cold_chain": True,
        "price_range": (3, 30),
        "products": [
            ("Tomatoes 1kg", "PROD-001", 7),
            ("Cucumber 500g", "PROD-002", 5),
            ("Onions 1kg", "PROD-003", 14),
            ("Bell Peppers Mix 500g", "PROD-004", 5),
            ("Bananas 1kg", "PROD-005", 5),
            ("Apples Red 1kg", "PROD-006", 14),
            ("Lettuce Head", "PROD-007", 5),
            ("Fresh Herbs Bundle", "PROD-008", 4),
            ("Lemons 500g", "PROD-009", 14),
            ("Carrots 1kg", "PROD-010", 10),
        ],
    },
    "Meat & Poultry": {
        "requires_cold_chain": True,
        "price_range": (30, 120),
        "products": [
            ("Chicken Breast 500g", "MEAT-001", 5),
            ("Ground Beef 500g", "MEAT-002", 5),
            ("Chicken Thighs 1kg", "MEAT-003", 5),
            ("Beef Steak 300g", "MEAT-004", 5),
            ("Chicken Wings 1kg", "MEAT-005", 5),
            ("Lamb Chops 500g", "MEAT-006", 5),
            ("Turkey Breast Slices 200g", "MEAT-007", 10),
            ("Beef Sausages 6pk", "MEAT-008", 14),
            ("Chicken Liver 500g", "MEAT-009", 4),
            ("Ground Lamb 500g", "MEAT-010", 5),
        ],
    },
    "Household": {
        "requires_cold_chain": False,
        "price_range": (10, 80),
        "products": [
            ("Dish Soap 500ml", "HOME-001", 730),
            ("All-Purpose Cleaner 750ml", "HOME-002", 730),
            ("Paper Towels 6 Roll", "HOME-003", 999),
            ("Toilet Paper 12 Roll", "HOME-004", 999),
            ("Trash Bags 30pk", "HOME-005", 999),
            ("Laundry Detergent 1L", "HOME-006", 730),
            ("Sponges Pack 4", "HOME-007", 999),
            ("Glass Cleaner 500ml", "HOME-008", 730),
            ("Air Freshener Spray", "HOME-009", 365),
            ("Aluminum Foil 30m", "HOME-010", 999),
        ],
    },
    "Personal Care": {
        "requires_cold_chain": False,
        "price_range": (10, 70),
        "products": [
            ("Shampoo 400ml", "PCAR-001", 365),
            ("Body Wash 500ml", "PCAR-002", 365),
            ("Toothpaste 100ml", "PCAR-003", 365),
            ("Deodorant Spray 150ml", "PCAR-004", 365),
            ("Hand Soap Liquid 300ml", "PCAR-005", 365),
            ("Facial Cleanser 200ml", "PCAR-006", 180),
            ("Moisturizer 100ml", "PCAR-007", 180),
            ("Sunscreen SPF50 100ml", "PCAR-008", 365),
            ("Cotton Pads 100pk", "PCAR-009", 999),
            ("Razor Blades 4pk", "PCAR-010", 999),
        ],
    },
    "Baby": {
        "requires_cold_chain": False,
        "price_range": (15, 90),
        "products": [
            ("Baby Diapers Size 3 40pk", "BABY-001", 999),
            ("Baby Wipes 80pk", "BABY-002", 365),
            ("Baby Formula 400g", "BABY-003", 180),
            ("Baby Food Pouch 120g", "BABY-004", 180),
            ("Baby Shampoo 300ml", "BABY-005", 365),
            ("Baby Lotion 200ml", "BABY-006", 365),
            ("Baby Bottle 250ml", "BABY-007", 999),
            ("Pacifier 2pk", "BABY-008", 999),
            ("Baby Cereal 200g", "BABY-009", 180),
            ("Diaper Rash Cream 100ml", "BABY-010", 365),
        ],
    },
}

ZONES = [
    {"name": "Maadi", "city": "Cairo", "delivery_fee": 25.0, "eta_min": 25},
    {"name": "Zamalek", "city": "Cairo", "delivery_fee": 30.0, "eta_min": 30},
    {"name": "Nasr City", "city": "Cairo", "delivery_fee": 20.0, "eta_min": 20},
    {"name": "Sheikh Zayed", "city": "Giza", "delivery_fee": 35.0, "eta_min": 35},
    {"name": "6th of October", "city": "Giza", "delivery_fee": 40.0, "eta_min": 40},
    {"name": "Heliopolis", "city": "Cairo", "delivery_fee": 25.0, "eta_min": 25},
    {"name": "Dokki", "city": "Giza", "delivery_fee": 20.0, "eta_min": 20},
    {"name": "New Cairo", "city": "Cairo", "delivery_fee": 30.0, "eta_min": 30},
    {"name": "Haram", "city": "Giza", "delivery_fee": 15.0, "eta_min": 20},
    {"name": "Shubra", "city": "Cairo", "delivery_fee": 20.0, "eta_min": 25},
]

STORES = [
    {"name": "DarkStore Maadi Hub", "city": "Cairo", "street": "Road 9, Maadi"},
    {"name": "DarkStore Nasr City Hub", "city": "Cairo", "street": "Abbas El-Akkad St"},
    {"name": "DarkStore Zamalek Hub", "city": "Cairo", "street": "26th of July St"},
    {
        "name": "DarkStore Sheikh Zayed Hub",
        "city": "Giza",
        "street": "Beverly Hills Entrance",
    },
    {
        "name": "DarkStore New Cairo Hub",
        "city": "Cairo",
        "street": "90th Street, 5th Settlement",
    },
]
