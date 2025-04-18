from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional, Dict, Union
import logging
from time import time
from fastapi import FastAPI, Response
from fastapi.encoders import jsonable_encoder
from cassis import load_typesystem
import time
from starlette.responses import PlainTextResponse, JSONResponse
import warnings
import re



class Settings(BaseSettings):
    # Name of this annotator
    annotator_name: str
    # Version of this annotator
    # TODO add these to the settings
    annotator_version: str
    # Log level
    log_level: str

    model_config = SettingsConfigDict(env_file=".env")


# Speech
class Speech(BaseModel):
    begin: int
    end: int


# Speaker
class Speaker(BaseModel):
    """
    Has to be in line with the features frim the typesystem
    """
    begin: int
    end: int
    label: str
    firstname: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    role: Optional[str] = None
    party: Optional[str] = None



# Load settings from env vars
settings = Settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

# Load the predefined typesystem that is needed for this annotator to work
typesystem_filename = '../resources/typesystem.xml'
logger.debug("Loading typesystem from \"%s\"", typesystem_filename)
with open(typesystem_filename, 'rb') as f:
    typesystem = load_typesystem(f)
    logger.debug("Base typesystem:")
    logger.debug(typesystem.to_xml())

# Load the Lua communication script
lua_communication_script_filename = "duui-parliament-segmenter.lua"
logger.debug("Loading Lua communication script from \"%s\"", lua_communication_script_filename)


# Request sent by DUUI
# Note, this is transformed by the Lua script
class DUUIRequest(BaseModel):
    # The texts language
    doc_len: int
    #
    lang: str
    #
    text: str

# Documentation response
class DUUIDocumentation(BaseModel):
    # Name of this annotator
    annotator_name: str

    # Version of this annotator
    version: str

    # Annotator implementation language (Python, Java, ...)
    implementation_lang: Optional[str]


# Response sent by DUUI
# Note, this is transformed by the Lua script
class DUUIResponse(BaseModel):
    speeches: List[Speech]
    speakers: List[Speaker]


app = FastAPI(
    openapi_url="/openapi.json",
    docs_url="/api",
    redoc_url=None,
    title=settings.annotator_name,
    description="Identification of structures from plenary minutes/plenary debates",
    version=settings.annotator_version,
    terms_of_service="https://www.texttechnologylab.org/legal_notice/",
    contact={
        "name": "Marius Liebald, Giuseppe Abrami",
        "url": "https://texttechnologylab.org",
        "email": "marius.liebald@ekhist.uu.se",
    },
    license_info={
        "name": "AGPL",
        "url": "http://www.gnu.org/licenses/agpl-3.0.en.html",
    },
)

with open(lua_communication_script_filename, 'rb') as f:
    lua_communication_script = f.read().decode("utf-8")
logger.debug("Lua communication script:")
logger.debug(lua_communication_script_filename)


# Get typesystem of this annotator
@app.get("/v1/typesystem")
def get_typesystem() -> Response:
    # TODO rimgve cassis dependency, as only needed for typesystem at the moment?
    xml = typesystem.to_xml()
    xml_content = xml.encode("utf-8")

    return Response(
        content=xml_content,
        media_type="application/xml"
    )


# Return Lua communication script
@app.get("/v1/communication_layer", response_class=PlainTextResponse)
def get_communication_layer() -> str:
    return lua_communication_script


# Return documentation info
@app.get("/v1/documentation")
def get_documentation():
    return DUUIDocumentation(
        annotator_name=settings.annotator_name,
        version=settings.annotator_version,
        implementation_lang="Python"
    )


# Get input / output of the annotator
@app.get("/v1/details/input_output")
def get_input_output() -> JSONResponse:
    json_item = {
        "inputs": [],
        "outputs": []
    }

    json_compatible_item_data = jsonable_encoder(json_item)
    return JSONResponse(content=json_compatible_item_data)



# Process request from DUUI
@app.post("/v1/process")
def post_process(request: DUUIRequest):
    import re

    # Step 1: flatten line breaks
    text = re.sub(r'\s*\n\s*', ' ', request.text)

    pattern = re.compile(
        r"""
        (?:
            (?P<title>Dr\.|Prof\.)\s*                # optional academic title (Dr., Prof.)
            (?P<speaker_name>[A-ZÄÖÜ][a-zäöüß]+)     # proper surname
            ,\s*
            (?P<role>                                 
                (?:[A-ZÄÖÜa-zäöüß(),\-]+\s*){1,10}    # role: 1–10 words max
            )
            :
        )
        |
        (?:
            (?P<president>Präsident(?:in)?)          # Präsident or Präsidentin
            :
        )
        """,
        re.VERBOSE
    )


    speeches = []
    speakers = []

    for match in pattern.finditer(text):
        begin = match.start()
        end = match.end()

        if match.group("speaker_name"):
            name = match.group("speaker_name")
            role = match.group("role").strip()
            title = match.group("title") or None
            label = f"{title + ' ' if title else ''}{name}, {role}"
        elif match.group("president"):
            name = match.group("president")
            role = "Präsident"
            title = None
            label = "Präsident"

        speakers.append(Speaker(
            begin=begin,
            end=end,
            label=label,
            firstname=None,
            name=name,
            title=title,
            role=role,
            party=None
        ))

        next_match = next(pattern.finditer(text, end), None)
        speech_end = next_match.start() if next_match else len(text)

        speeches.append(Speech(
            begin=end,
            end=speech_end,
            speaker=len(speakers) - 1
        ))

    return DUUIResponse(
        speeches=speeches,
        speakers=speakers
    )
