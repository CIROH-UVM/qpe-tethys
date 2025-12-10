from tethys_sdk.components import ComponentBase


class App(ComponentBase):
    """
    Tethys app class for Geoglows Tutorial.
    """

    name = "Geoglows Tutorial"
    description = ""
    package = "geoglows_tutorial"  # WARNING: Do not change this value
    index = "home"
    icon = f"{package}/images/icon.png"
    root_url = "geoglows-tutorial"
    color = "#c0392b"
    tags = ""
    enable_feedback = False
    feedback_emails = []
    exit_url = "/apps/"
    default_layout = "NavHeader"
    nav_links = "auto"


@App.page
def home(lib):
    return lib.tethys.Display(
        lib.tethys.Map(
            lib.ol.layer.Image(title="GEOGLOWS Streamflow Service")(
                lib.ol.source.ImageArcGISRest(
                    url='https://livefeeds3.arcgis.com/arcgis/rest/services/GEOGLOWS/GlobalWaterModel_Medium/MapServer'
                )
            )
        )
    )