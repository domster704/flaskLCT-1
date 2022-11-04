import cloudscraper
from flask import request, jsonify
from flask_restful import Resource

from options.correct_params import CorrectParam
from options.yandex_geo import YandexGeo


class CianParserApi(Resource):
    # @jwt_required() - убрать, когда сделают авторизацию
    def post(self):
        args = request.json
        cianParser = CianParser(args)
        return jsonify(cianParser.parse())


class CianParser(object):
    def __init__(self, dictWithData: dict):
        self.__cloudscraper = cloudscraper.create_scraper()
        self.__cloudscraper.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36"
        }
        self.__geocodeID: int = 0
        self.__flatParams: dict = {}

        # ------------- Обязательные параметры ---------------
        self.__address: str = "".join(dictWithData["address"].split(',')[:-1])
        self.__rooms: int = 9 if type(dictWithData["room"]) == str and str(
            dictWithData["room"]).lower() == "студия" else int(dictWithData["room"])
        self.__segment: str = str(dictWithData["segment"]).lower()
        self.__maxFloor: int = dictWithData["maxFloor"]
        self.__material: str = str(dictWithData["material"]).lower()

        self.__coordinates: dict = YandexGeo(dictWithData["address"]).getCoords()
        self.__objectData: dict = {**dictWithData, **self.__coordinates}

        # ------------- Корректирующие параметры -------------
        self.__flatFloor: int = dictWithData["correctFloor"]
        self.__flatArea: str = dictWithData["correctArea"]
        self.__flatKitchenArea: str = dictWithData["correctKitchenArea"]
        self.__flatBalcony: bool = True if str(dictWithData["correctBalcony"]).lower() == "да" else False
        self.__metroTime: int = dictWithData["correctMetroTime"]
        self.__flatStatusFinish: str = str(dictWithData["correctStatusFinish"]).lower()

        # ------------- Индексы корректирующих параметров -------------
        self.__typeOfEvalFloor: int = CorrectParam.getTypeOfFloor(self.__flatFloor, self.__maxFloor)
        self.__typeOfEvalArea: int = CorrectParam.getTypeOfArea(float(self.__flatArea))
        self.__typeOfEvalKitchenArea: int = CorrectParam.getTypeOfKitchenArea(float(self.__flatKitchenArea))
        self.__typeOfEvalBalcony: int = CorrectParam.getTypeOfBalcony(self.__flatBalcony)
        self.__typeOfEvalMetroTime: int = CorrectParam.getTypeOfMetroTime(self.__metroTime)
        self.__typeOfEvalStatusFinish: int = CorrectParam.getTypeOfStatusFinish(self.__flatStatusFinish)

    def parse(self):
        self.__geoID(self.__address)
        self.__readFlatsParamsFromJson()
        return self.__flatParams

    def __geoID(self, addressInputted: str):
        """
        :param addressInputted: адрес, который мы получаем из таблицы на фронте.
        e.g. address = г. Москва, ул. Ватутина, д. 11
        """

        def getCoord() -> list:
            """
            :return: список из координат формата [x, y]
            """
            linkForGetCoord = f"https://www.cian.ru/api/geo/geocode-cached/?request={addressInputted}"
            responseForGetCoord = self.__cloudscraper.get(linkForGetCoord)
            return responseForGetCoord.json()["items"][0]

        data = getCoord()
        linkForGetGeoID = "https://www.cian.ru/api/geo/geocoded-for-search/"
        responseForGetGeoID = self.__cloudscraper.post(linkForGetGeoID, json={
            "Lng": data["coordinates"][0],
            "Lat": data["coordinates"][1],
            "Kind": data["kind"],
            "Address": data["text"]
        })

        self.__geocodeID = responseForGetGeoID.json()["details"][1]["id"]

    def __readFlatsParamsFromJson(self):
        """
        Функция, которая считывает данные о квартирах с json файла
        """

        houseMaterialsId = {
            "кирпич": 1,
            "brick": 1,
            "монолит": 2,
            "monolith": 2,
            "панель": 3,
            "panel": 3
        }

        segmentId = {
            "старый жилой фонд": 1,
            "oldhousingstock": 1,
            "современное жилье": 1,
            "современное жильё": 1,
            "modernhousing": 1,
            "новостройка": 2,
            "newbuilding": 2,
        }

        linkOfOffers = "https://api.cian.ru/search-offers/v2/search-offers-desktop/"
        responseOfOffers = self.__cloudscraper.post(linkOfOffers, json={
            "jsonQuery": {
                "_type": "flatsale",
                "engine_version": {
                    "type": "term",
                    "value": 2
                },
                "geo": {
                    "type": "geo",
                    "value": [{
                        "type": "street",
                        "id": self.__geocodeID
                    }]
                },
                "room": {
                    "type": "terms",
                    "value": [
                        int(self.__rooms)
                    ]
                },
                "house_material": {
                    "type": "terms",
                    "value": [
                        houseMaterialsId[self.__material]
                    ]
                },
                "building_status": {
                    "type": "term",
                    "value": segmentId[self.__segment]
                },
                "floor": {
                    "type": "range",
                    "value": {
                        "gte": 0,
                        "lte": self.__maxFloor
                    }
                },
                "region": {
                    "type": "terms",
                    "value": [
                        1
                    ]
                }
            }
        })

        # кол-во выдаваемых аналогов
        MAX_COUNT_OF_ANALOGS = 7

        count: int = 0
        analogsList = []
        for name in ["offersSerialized", "suggestOffersSerializedList"]:
            if count == MAX_COUNT_OF_ANALOGS:
                break
            for elem in responseOfOffers.json()["data"][name]:
                if count == MAX_COUNT_OF_ANALOGS:
                    break

                metroTime: int = 100000
                for metroData in elem["geo"]["undergrounds"]:
                    metroTime = min(metroData["time"], metroTime)

                floor: int = elem["floorNumber"]
                maxFloor: int = elem["building"]["floorsCount"]
                area: str = elem["totalArea"]
                kitchenArea: str = elem["kitchenArea"]
                isThereBalcony: bool = True if type(elem["balconiesCount"]) is int and elem[
                    "balconiesCount"] > 0 else False

                kitchenArea = self.__flatKitchenArea if kitchenArea is None else kitchenArea

                data = {
                    "address": elem["geo"]["userInput"],
                    "price": elem["bargainTerms"]["price"],
                    "roomsCount": elem["roomsCount"],
                    "floor": floor,
                    "maxFloor": maxFloor,
                    "material": elem["building"]["materialType"],
                    "area": area,
                    "kitchenArea": kitchenArea,
                    "balcony": str(isThereBalcony),
                    "metroTime": metroTime,
                    "segment": self.__segment,
                    "typeOfFloor": [
                        self.__typeOfEvalFloor,
                        CorrectParam.getTypeOfFloor(floor, maxFloor)
                    ],
                    "typeOfArea": [
                        self.__typeOfEvalArea,
                        CorrectParam.getTypeOfArea(float(area))
                    ],
                    "typeOfKitchenArea": [
                        self.__typeOfEvalKitchenArea,
                        CorrectParam.getTypeOfKitchenArea(float(kitchenArea))
                    ],
                    "typeOfBalcony": [
                        self.__typeOfEvalBalcony,
                        CorrectParam.getTypeOfBalcony(isThereBalcony)
                    ],
                    "typeOfMetroTime": [
                        self.__typeOfEvalMetroTime,
                        CorrectParam.getTypeOfMetroTime(metroTime)
                    ],
                    "typeOfStatusFinish": [
                        self.__typeOfEvalStatusFinish,
                        self.__typeOfEvalStatusFinish
                    ],
                    "location": {
                        "lat": str(elem["geo"]["coordinates"]["lat"]),
                        "lng": str(elem["geo"]["coordinates"]["lng"]),
                    }
                }
                count += 1

                analogsList.append(data)
        self.__flatParams = {
            "standard": self.__objectData,
            "analogs": analogsList
        }
