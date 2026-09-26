import ro_boot  # noqa
from app.services.location_utils import location_tokens
for s in ["Warszawa", "Warsaw", "Warsaw, Poland", "Gdańsk", "Gdansk", "Gdansk or Warsaw", "Gdańsk, Gdynia, Warsaw", "Kraków", "Krakow", "Wrocław", "Wroclaw", "Łódź", "Lodz", "Piaseczno", "Poznań"]:
    print(repr(s), sorted(location_tokens(s)))
