from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timedelta
from typing import Any, ClassVar

import rstr

from sqlseed.generators._dispatch import GeneratorDispatchMixin
from sqlseed.generators._json_helpers import generate_json_from_schema
from sqlseed.generators._string_helpers import generate_random_string


class BaseProvider(GeneratorDispatchMixin):
    """Built-in data generator with no external dependencies."""

    FIRST_NAMES: ClassVar[list[str]] = [
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
    LAST_NAMES: ClassVar[list[str]] = [
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

    def _gen_string(
        self,
        *,
        min_length: int = 1,
        max_length: int = 100,
        charset: str | None = None,
    ) -> str:
        return generate_random_string(self._rng, min_length=min_length, max_length=max_length, charset=charset)

    def _gen_integer(self, *, min_value: int = 0, max_value: int = 999999) -> int:
        return self._rng.randint(min_value, max_value)

    def _gen_float(
        self,
        *,
        min_value: float = 0.0,
        max_value: float = 999999.0,
        precision: int = 2,
    ) -> float:
        value = self._rng.uniform(min_value, max_value)
        return round(value, precision)

    def _gen_boolean(self) -> bool:
        return self._rng.choice([True, False])

    def _gen_bytes(self, *, length: int = 16) -> bytes:
        return self._rng.randbytes(length)

    def _gen_name(self) -> str:
        return f"{self._rng.choice(self.FIRST_NAMES)} {self._rng.choice(self.LAST_NAMES)}"

    def _gen_first_name(self) -> str:
        return self._rng.choice(self.FIRST_NAMES)

    def _gen_last_name(self) -> str:
        return self._rng.choice(self.LAST_NAMES)

    def _gen_email(self) -> str:
        first = self._gen_first_name().lower()
        last = self._gen_last_name().lower()
        domains = ["example.com", "test.org", "mail.net", "demo.io", "sample.dev"]
        return f"{first}.{last}{self._rng.randint(1, 999)}@{self._rng.choice(domains)}"

    def _gen_phone(self) -> str:
        area = self._rng.randint(200, 999)
        mid = self._rng.randint(100, 999)
        end = self._rng.randint(1000, 9999)
        return f"{area}-{mid}-{end}"

    def _gen_address(self) -> str:
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
        num = self._rng.randint(1, 9998)
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
        street = self._rng.choice(streets)
        city = self._rng.choice(cities)
        state = self._rng.choice(states)
        return f"{num} {street}, {city}, {state}"

    def _gen_company(self) -> str:
        prefixes = ["Global", "Prime", "Alpha", "Elite", "Tech", "Nova", "Apex", "Core"]
        suffixes = ["Corp", "Inc", "LLC", "Ltd", "Group", "Systems", "Solutions", "Labs"]
        return f"{self._rng.choice(prefixes)} {self._rng.choice(suffixes)}"

    def _gen_url(self) -> str:
        domains = ["example", "test", "demo", "sample", "mysite"]
        tlds = ["com", "org", "net", "io", "dev"]
        paths = ["", "/home", "/about", "/products", "/blog", "/api/v1"]
        domain = self._rng.choice(domains)
        tld = self._rng.choice(tlds)
        path = self._rng.choice(paths)
        return f"https://www.{domain}.{tld}{path}"

    def _gen_ipv4(self) -> str:
        o1 = self._rng.randint(1, 255)
        o2 = self._rng.randint(0, 255)
        o3 = self._rng.randint(0, 255)
        o4 = self._rng.randint(1, 254)
        return f"{o1}.{o2}.{o3}.{o4}"

    def _gen_uuid(self) -> str:
        return str(uuid.UUID(bytes=self._rng.randbytes(16), version=4))

    def _gen_date(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        return self._random_date(start_year, end_year).strftime("%Y-%m-%d")

    def _gen_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        start = datetime(start_year, 1, 1)
        end = datetime(resolved_end, 12, 31, 23, 59, 59)
        delta = max((end - start).total_seconds(), 0)
        random_dt = start + timedelta(seconds=self._rng.uniform(0, max(delta, 1)))
        return random_dt.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _resolve_date_range(start_year: int, end_year: int | None) -> tuple[int, int]:
        resolved_end = end_year or datetime.now().year
        return start_year, max(resolved_end, start_year)

    def _random_date(self, start_year: int, end_year: int | None = None) -> datetime:
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        start = datetime(start_year, 1, 1)
        end = datetime(resolved_end, 12, 31)
        delta = max((end - start).days, 0)
        return start + timedelta(days=self._rng.randint(0, max(delta, 1)))

    def _gen_timestamp(self) -> int:
        start = datetime(2000, 1, 1)
        end = datetime(2030, 12, 31, 23, 59, 59)
        delta = (end - start).total_seconds()
        random_dt = start + timedelta(seconds=self._rng.uniform(0, delta))
        return int(random_dt.timestamp())

    def _gen_text(self, *, min_length: int = 50, max_length: int = 200) -> str:
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

    def _gen_sentence(self) -> str:
        subjects = ["The system", "A user", "The process", "An event", "The service"]
        verbs = ["completed", "started", "failed", "succeeded", "processed"]
        objects = ["the operation", "a request", "the task", "an update", "the transaction"]
        return f"{self._rng.choice(subjects)} {self._rng.choice(verbs)} {self._rng.choice(objects)}."

    def _gen_password(self, *, length: int = 16) -> str:
        chars = string.ascii_letters + string.digits + string.punctuation
        return "".join(self._rng.choice(chars) for _ in range(length))

    def _gen_choice(self, choices: list[Any]) -> Any:
        return self._rng.choice(choices)

    def _gen_json(self, *, schema: dict[str, Any] | None = None) -> str:
        return generate_json_from_schema(self, schema, self._get_array_count)

    def _get_array_count(self) -> int:
        return self._rng.randint(1, 5)

    def _gen_pattern(self, *, regex: str) -> str:
        r = rstr.Rstr(self._rng)
        return r.xeger(regex)

    CITIES: ClassVar[list[str]] = [
        "New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
        "San Antonio", "San Diego", "Dallas", "San Jose", "Austin",
        "Jacksonville", "Fort Worth", "Columbus", "Charlotte", "Indianapolis",
        "San Francisco", "Seattle", "Denver", "Washington", "Nashville",
        "Oklahoma City", "El Paso", "Boston", "Portland", "Las Vegas",
        "Memphis", "Louisville", "Baltimore", "Milwaukee", "Albuquerque",
        "Tucson", "Fresno", "Sacramento", "Mesa", "Atlanta",
        "Kansas City", "Colorado Springs", "Raleigh", "Omaha", "Miami",
        "Long Beach", "Virginia Beach", "Oakland", "Minneapolis", "Tulsa",
        "Arlington", "Tampa", "New Orleans", "London", "Paris",
        "Tokyo", "Berlin", "Sydney", "Toronto", "Vancouver",
    ]

    COUNTRIES: ClassVar[list[str]] = [
        "United States", "United Kingdom", "Canada", "Australia", "Germany",
        "France", "Japan", "Brazil", "India", "China",
        "Italy", "Spain", "Mexico", "South Korea", "Netherlands",
        "Sweden", "Norway", "Denmark", "Finland", "Switzerland",
        "Austria", "Belgium", "Portugal", "Ireland", "New Zealand",
        "Singapore", "Argentina", "Chile", "Colombia", "Peru",
        "Poland", "Czech Republic", "Romania", "Hungary", "Greece",
        "Turkey", "Thailand", "Vietnam", "Philippines", "Malaysia",
        "Indonesia", "Egypt", "South Africa", "Nigeria", "Kenya",
        "Israel", "United Arab Emirates", "Saudi Arabia", "Russia", "Ukraine",
    ]

    STATES: ClassVar[list[str]] = [
        "Alabama", "Alaska", "Arizona", "Arkansas", "California",
        "Colorado", "Connecticut", "Delaware", "Florida", "Georgia",
        "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa",
        "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
        "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
        "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
        "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
        "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
        "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
        "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
    ]

    JOB_TITLES: ClassVar[list[str]] = [
        "Software Engineer", "Data Scientist", "Product Manager", "Designer",
        "Marketing Manager", "Sales Representative", "Business Analyst",
        "Project Manager", "DevOps Engineer", "QA Engineer",
        "Frontend Developer", "Backend Developer", "Full Stack Developer",
        "Mobile Developer", "Machine Learning Engineer", "Security Analyst",
        "Database Administrator", "System Administrator", "Technical Writer",
        "UX Researcher", "Scrum Master", "Engineering Manager",
        "HR Manager", "Financial Analyst", "Accountant",
        "Consultant", "Architect", "Director of Operations",
        "Chief Technology Officer", "Chief Executive Officer",
        "Registered Nurse", "Teacher", "Lawyer",
        "Graphic Designer", "Content Writer", "Social Media Manager",
        "Customer Support Specialist", "Operations Manager", "Supply Chain Analyst",
        "Research Scientist", "Civil Engineer", "Mechanical Engineer",
        "Electrical Engineer", "Chemist", "Biologist",
        "Pharmacist", "Physician", "Dentist",
        "Veterinarian", "Pilot",
    ]

    COUNTRY_CODES: ClassVar[list[str]] = [
        "US", "GB", "CA", "AU", "DE", "FR", "JP", "BR", "IN", "CN",
        "IT", "ES", "MX", "KR", "NL", "SE", "NO", "DK", "FI", "CH",
        "AT", "BE", "PT", "IE", "NZ", "SG", "AR", "CL", "CO", "PE",
        "PL", "CZ", "RO", "HU", "GR", "TR", "TH", "VN", "PH", "MY",
        "ID", "EG", "ZA", "NG", "KE", "IL", "AE", "SA", "RU", "UA",
    ]

    def _gen_username(self) -> str:
        first = self._gen_first_name()
        last = self._gen_last_name()
        fmt = self._rng.choice([
            "first_last", "first.dot", "firstlast", "firstN",
            "first_lastN", "First Last", "first last", "firstlastN",
        ])
        if fmt == "first_last":
            return f"{first.lower()}_{last.lower()}"
        if fmt == "first.dot":
            return f"{first.lower()}.{last.lower()}"
        if fmt == "firstlast":
            return f"{first.lower()}{last.lower()}"
        if fmt == "firstN":
            return f"{first.lower()}{self._rng.randint(1, 999)}"
        if fmt == "first_lastN":
            return f"{first.lower()}_{last.lower()}{self._rng.randint(1, 99)}"
        if fmt == "First Last":
            return f"{first} {last}"
        if fmt == "first last":
            return f"{first.lower()} {last.lower()}"
        return f"{first.lower()}{last.lower()}{self._rng.randint(1, 999)}"

    def _gen_city(self) -> str:
        return self._rng.choice(self.CITIES)

    def _gen_country(self) -> str:
        return self._rng.choice(self.COUNTRIES)

    def _gen_state(self) -> str:
        return self._rng.choice(self.STATES)

    def _gen_zip_code(self) -> str:
        return f"{self._rng.randint(10000, 99999)}"

    def _gen_job_title(self) -> str:
        return self._rng.choice(self.JOB_TITLES)

    def _gen_country_code(self) -> str:
        return self._rng.choice(self.COUNTRY_CODES)
