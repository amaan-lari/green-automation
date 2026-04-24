import random
import re
from typing import List

INDIAN_MOBILE_REGEX = re.compile(r'^(\+91[\-\s]?)?[0]?(91)?[6789]\d{9}$')


def generate_indian_phone_numbers(count: int) -> List[str]:
    """
    Generate `count` unique valid Indian mobile numbers in +91XXXXXXXXXX format.
    Numbers start with 6, 7, 8, or 9 and are exactly 10 digits.
    """
    generated = set()

    while len(generated) < count:
        first_digit = random.choice('6789')
        remaining = ''.join(random.choices('0123456789', k=9))
        number = f"+91{first_digit}{remaining}"

        if INDIAN_MOBILE_REGEX.match(number) and number not in generated:
            generated.add(number)

    return list(generated)


if __name__ == "__main__":
    samples = generate_indian_phone_numbers(10)
    for number in samples:
        print(number)