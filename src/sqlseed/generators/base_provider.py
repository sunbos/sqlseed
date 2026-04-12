from __future__ import annotations

import json
import random
import string
import uuid
from datetime import datetime, timedelta
from typing import Any


class BaseProvider:
    """Built-in data generator with no external dependencies."""

    def __init__(self) -> None:
        self._rng = random.Random()
        self._locale: str = "en_US"

    @property
    def name(self) -> str:
        return "base"

    def set_locale(self, locale: str) -> None:
        self._locale = locale

    def set_seed(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def generate_string(
        self,
        *,
        min_length: int = 1,
        max_length: int = 100,
        charset: str | None = None,
    ) -> str:
        if charset == "alphanumeric":
            chars = string.ascii_letters + string.digits
        elif charset == "alpha":
            chars = string.ascii_letters
        elif charset == "digits":
            chars = string.digits
        elif charset is not None:
            chars = charset
        else:
            chars = string.ascii_letters + string.digits + " _-"
        length = self._rng.randint(min_length, max_length)
        return "".join(self._rng.choice(chars) for _ in range(length))

    def generate_integer(self, *, min_value: int = 0, max_value: int = 999999) -> int:
        return self._rng.randint(min_value, max_value)

    def generate_float(
        self,
        *,
        min_value: float = 0.0,
        max_value: float = 999999.0,
        precision: int = 2,
    ) -> float:
        value = self._rng.uniform(min_value, max_value)
        return round(value, precision)

    def generate_boolean(self) -> bool:
        return self._rng.choice([True, False])

    def generate_bytes(self, *, length: int = 16) -> bytes:
        return self._rng.randbytes(length)

    def generate_name(self) -> str:
        first_names = [
            "James",
            "Mary",
            "John",
            "Patricia",
            "Robert",
            "Jennifer",
            "Michael",
            "Linda",
            "William",
            "Elizabeth",
            "David",
            "Barbara",
            "Richard",
            "Susan",
            "Joseph",
            "Jessica",
            "Thomas",
            "Sarah",
            "Charles",
            "Karen",
            "Christopher",
            "Lisa",
            "Daniel",
            "Nancy",
            "Matthew",
            "Betty",
            "Anthony",
            "Margaret",
            "Mark",
            "Sandra",
            "Donald",
            "Ashley",
            "Steven",
            "Kimberly",
            "Paul",
            "Emily",
            "Andrew",
            "Donna",
            "Joshua",
            "Michelle",
            "Kenneth",
            "Carol",
            "Kevin",
            "Amanda",
            "Brian",
            "Dorothy",
            "George",
            "Melissa",
            "Timothy",
            "Deborah",
            "Ronald",
            "Stephanie",
            "Edward",
            "Rebecca",
            "Jason",
            "Sharon",
            "Jeffrey",
            "Laura",
            "Ryan",
            "Cynthia",
        ]
        last_names = [
            "Smith",
            "Johnson",
            "Williams",
            "Brown",
            "Jones",
            "Garcia",
            "Miller",
            "Davis",
            "Rodriguez",
            "Martinez",
            "Hernandez",
            "Lopez",
            "Gonzalez",
            "Wilson",
            "Anderson",
            "Thomas",
            "Taylor",
            "Moore",
            "Jackson",
            "Martin",
            "Lee",
            "Perez",
            "Thompson",
            "White",
            "Harris",
            "Sanchez",
            "Clark",
            "Ramirez",
            "Lewis",
            "Robinson",
            "Walker",
            "Young",
            "Allen",
            "King",
            "Wright",
            "Scott",
            "Torres",
            "Nguyen",
            "Hill",
            "Flores",
            "Green",
            "Adams",
            "Nelson",
            "Baker",
            "Hall",
            "Rivera",
            "Campbell",
            "Mitchell",
            "Carter",
            "Roberts",
            "Gomez",
            "Phillips",
            "Evans",
            "Turner",
            "Diaz",
            "Parker",
            "Cruz",
            "Edwards",
            "Collins",
            "Reyes",
        ]
        return f"{self._rng.choice(first_names)} {self._rng.choice(last_names)}"

    def generate_first_name(self) -> str:
        names = [
            "James",
            "Mary",
            "John",
            "Patricia",
            "Robert",
            "Jennifer",
            "Michael",
            "Linda",
            "William",
            "Elizabeth",
            "David",
            "Barbara",
            "Richard",
            "Susan",
            "Joseph",
            "Jessica",
            "Thomas",
            "Sarah",
            "Charles",
            "Karen",
            "Christopher",
            "Lisa",
            "Daniel",
            "Nancy",
            "Matthew",
            "Betty",
            "Anthony",
            "Margaret",
            "Mark",
            "Sandra",
        ]
        return self._rng.choice(names)

    def generate_last_name(self) -> str:
        names = [
            "Smith",
            "Johnson",
            "Williams",
            "Brown",
            "Jones",
            "Garcia",
            "Miller",
            "Davis",
            "Rodriguez",
            "Martinez",
            "Hernandez",
            "Lopez",
            "Gonzalez",
            "Wilson",
            "Anderson",
            "Thomas",
            "Taylor",
            "Moore",
            "Jackson",
            "Martin",
            "Lee",
            "Perez",
            "Thompson",
            "White",
            "Harris",
            "Sanchez",
            "Clark",
            "Ramirez",
            "Lewis",
            "Robinson",
        ]
        return self._rng.choice(names)

    def generate_email(self) -> str:
        first = self.generate_first_name().lower()
        last = self.generate_last_name().lower()
        domains = ["example.com", "test.org", "mail.net", "demo.io", "sample.dev"]
        return f"{first}.{last}{self._rng.randint(1, 999)}@{self._rng.choice(domains)}"

    def generate_phone(self) -> str:
        area = self._rng.randint(200, 999)
        mid = self._rng.randint(100, 999)
        end = self._rng.randint(1000, 9999)
        return f"{area}-{mid}-{end}"

    def generate_address(self) -> str:
        streets = [
            "Main St",
            "Oak Ave",
            "Pine Rd",
            "Elm Blvd",
            "Cedar Ln",
            "Maple Dr",
            "Washington Ave",
            "Park Rd",
            "Lake Dr",
            "Hill St",
        ]
        numbers = list(range(1, 9999))
        cities = [
            "Springfield",
            "Portland",
            "Franklin",
            "Clinton",
            "Madison",
            "Georgetown",
            "Arlington",
            "Salem",
            "Fairview",
            "Chester",
        ]
        states = ["CA", "NY", "TX", "FL", "IL", "PA", "OH", "GA", "NC", "MI"]
        num = self._rng.choice(numbers)
        street = self._rng.choice(streets)
        city = self._rng.choice(cities)
        state = self._rng.choice(states)
        return f"{num} {street}, {city}, {state}"

    def generate_company(self) -> str:
        prefixes = ["Global", "Prime", "Alpha", "Elite", "Tech", "Nova", "Apex", "Core"]
        suffixes = ["Corp", "Inc", "LLC", "Ltd", "Group", "Systems", "Solutions", "Labs"]
        return f"{self._rng.choice(prefixes)} {self._rng.choice(suffixes)}"

    def generate_url(self) -> str:
        domains = ["example", "test", "demo", "sample", "mysite"]
        tlds = ["com", "org", "net", "io", "dev"]
        paths = ["", "/home", "/about", "/products", "/blog", "/api/v1"]
        domain = self._rng.choice(domains)
        tld = self._rng.choice(tlds)
        path = self._rng.choice(paths)
        return f"https://www.{domain}.{tld}{path}"

    def generate_ipv4(self) -> str:
        o1 = self._rng.randint(1, 255)
        o2 = self._rng.randint(0, 255)
        o3 = self._rng.randint(0, 255)
        o4 = self._rng.randint(1, 254)
        return f"{o1}.{o2}.{o3}.{o4}"

    def generate_uuid(self) -> str:
        return str(uuid.UUID(bytes=self._rng.randbytes(16), version=4))

    def generate_date(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        if end_year is None:
            end_year = datetime.now().year
        end_year = max(end_year, start_year)
        start = datetime(start_year, 1, 1)
        end = datetime(end_year, 12, 31)
        delta = max((end - start).days, 0)
        random_date = start + timedelta(days=self._rng.randint(0, max(delta, 1)))
        return random_date.strftime("%Y-%m-%d")

    def generate_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        if end_year is None:
            end_year = datetime.now().year
        end_year = max(end_year, start_year)
        start = datetime(start_year, 1, 1)
        end = datetime(end_year, 12, 31, 23, 59, 59)
        delta = max((end - start).total_seconds(), 0)
        random_dt = start + timedelta(seconds=self._rng.uniform(0, max(delta, 1)))
        return random_dt.strftime("%Y-%m-%d %H:%M:%S")

    def generate_timestamp(self) -> int:
        start = datetime(2000, 1, 1)
        end = datetime(2030, 12, 31, 23, 59, 59)
        delta = (end - start).total_seconds()
        random_dt = start + timedelta(seconds=self._rng.uniform(0, delta))
        return int(random_dt.timestamp())

    def generate_text(self, *, min_length: int = 50, max_length: int = 200) -> str:
        words = [
            "lorem",
            "ipsum",
            "dolor",
            "sit",
            "amet",
            "consectetur",
            "adipiscing",
            "elit",
            "sed",
            "do",
            "eiusmod",
            "tempor",
            "incididunt",
            "ut",
            "labore",
            "et",
            "dolore",
            "magna",
            "aliqua",
            "enim",
            "ad",
            "minim",
            "veniam",
            "quis",
            "nostrud",
            "exercitation",
            "ullamco",
            "laboris",
            "nisi",
        ]
        length = self._rng.randint(min_length, max_length)
        result = ""
        while len(result) < length:
            word = self._rng.choice(words)
            if result:
                result += " "
            result += word
        return result[:length]

    def generate_sentence(self) -> str:
        subjects = ["The system", "A user", "The process", "An event", "The service"]
        verbs = ["completed", "started", "failed", "succeeded", "processed"]
        objects = ["the operation", "a request", "the task", "an update", "the transaction"]
        return f"{self._rng.choice(subjects)} {self._rng.choice(verbs)} {self._rng.choice(objects)}."

    def generate_password(self, *, length: int = 16) -> str:
        chars = string.ascii_letters + string.digits + string.punctuation
        return "".join(self._rng.choice(chars) for _ in range(length))

    def generate_choice(self, choices: list[Any]) -> Any:
        return self._rng.choice(choices)

    def generate_json(self, *, schema: dict[str, Any] | None = None) -> str:
        if schema is None:
            data = {
                "id": self.generate_integer(min_value=1, max_value=999999),
                "name": self.generate_name(),
                "active": self.generate_boolean(),
            }
        else:
            data = self._generate_from_schema(schema)
        return json.dumps(data)

    def _generate_from_schema(self, schema: dict[str, Any]) -> Any:
        schema_type = schema.get("type", "string")
        if schema_type == "string":
            return self.generate_string(min_length=5, max_length=20)
        if schema_type == "integer":
            return self.generate_integer()
        if schema_type == "number":
            return self.generate_float()
        if schema_type == "boolean":
            return self.generate_boolean()
        if schema_type == "array":
            items = schema.get("items", {"type": "string"})
            count = self._rng.randint(1, 5)
            return [self._generate_from_schema(items) for _ in range(count)]
        if schema_type == "object":
            properties = schema.get("properties", {})
            return {k: self._generate_from_schema(v) for k, v in properties.items()}
        return self.generate_string()
