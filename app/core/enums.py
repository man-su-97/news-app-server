
from enum import IntEnum


class CategoryEnum(IntEnum):
    VIOLENT_CRIME = 1
    TERRORISM = 2
    FINANCIAL_CRIME = 3
    CYBER_CRIME = 4
    DRUG_CRIME = 5
    PROPERTY_CRIME = 6
    SEXUAL_CRIME = 7
    OTHER = 8


class SubCategoryEnum(IntEnum):
    MURDER = 1
    VIOLENCE = 2   
    TERRORISM = 3  
    FRAUD = 4   
    CORRUPTION = 5   
    CYBERCRIME = 6   
    DRUG_TRAFFICKING = 7   
    THEFT = 8   
    HUMAN_TRAFFICKING = 9   
    OTHER = 10  


AI_STRING_TO_SUB_CATEGORY: dict[str, SubCategoryEnum] = {
    "murder":      SubCategoryEnum.MURDER,
    "violence":    SubCategoryEnum.VIOLENCE,
    "terrorism":   SubCategoryEnum.TERRORISM,
    "fraud":       SubCategoryEnum.FRAUD,
    "corruption":  SubCategoryEnum.CORRUPTION,
    "cybercrime":  SubCategoryEnum.CYBERCRIME,
    "drugs":       SubCategoryEnum.DRUG_TRAFFICKING,
    "theft":       SubCategoryEnum.THEFT,
    "trafficking": SubCategoryEnum.HUMAN_TRAFFICKING,
    "other":       SubCategoryEnum.OTHER,
}


SUB_CATEGORY_TO_CATEGORY: dict[SubCategoryEnum, CategoryEnum] = {
    SubCategoryEnum.MURDER:            CategoryEnum.VIOLENT_CRIME,
    SubCategoryEnum.VIOLENCE:          CategoryEnum.VIOLENT_CRIME,
    SubCategoryEnum.TERRORISM:         CategoryEnum.TERRORISM,
    SubCategoryEnum.FRAUD:             CategoryEnum.FINANCIAL_CRIME,
    SubCategoryEnum.CORRUPTION:        CategoryEnum.FINANCIAL_CRIME,
    SubCategoryEnum.CYBERCRIME:        CategoryEnum.CYBER_CRIME,
    SubCategoryEnum.DRUG_TRAFFICKING:  CategoryEnum.DRUG_CRIME,
    SubCategoryEnum.THEFT:             CategoryEnum.PROPERTY_CRIME,
    SubCategoryEnum.HUMAN_TRAFFICKING: CategoryEnum.SEXUAL_CRIME,
    SubCategoryEnum.OTHER:             CategoryEnum.OTHER,
}
