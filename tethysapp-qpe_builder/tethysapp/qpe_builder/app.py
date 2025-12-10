from tethys_sdk.components import ComponentBase


class App(ComponentBase):
    """
    Tethys app class for QPE Builder.
    """

    name = "QPE Builder"
    description = "Develop, run, and save custom workflows for generating regional Quantitative Precipitation Estimates (QPE)"
    package = "qpe_builder"  # WARNING: Do not change this value
    index = "home"
    icon = f"{package}/images/CIROHLogo_200x200.png"
    root_url = "qpe-builder"
    color = "#0073FF"
    tags = "Meteorology", "Precipitation Estimate", "Forecasts", "Workflows"
    enable_feedback = False
    feedback_emails = []
    exit_url = "/apps/"
    default_layout = "NavHeader"
    nav_links = "auto"


@App.page
def home(lib):
    # tif_source = lib.ol.source.GeoTIFF.SourceInfo(
    #     url="/static/qpe_builder/data/radar_data.tif",
    #     min=-1.0,
    #     max=1.0)
    # lib.register(
    #     'ol@10.6.0',
    #     'olcore',
    #     default_export="ol"
    # )
    
    # VectorSource = lib.ol.source.Vector()
    # print(type(VectorSource))

    # point = lib.ol.Feature(name="New York City", geometry=lib.ol.geom.Point([-8238310.235647004, 4970071.579142427]))
    #VectorSource.addFeature(point)
    
    return lib.tethys.Display(
        lib.tethys.Map(
            lib.ol.layer.Image(title="Radar Reflectivity", opacity=0.8)(
                lib.ol.source.ImageStatic(
                    url="/static/qpe_builder/data/radar_overlay.png",
                    imageExtent=[-14470977.205671597, 2273623.3735015886, -6679726.267689361, 7360895.77546744]
                )
            )
        )
    )


# try using geotiff.js 
# @App.page
# def home(lib):
#     lib.register(
#         'geotiff.js@1.0.1',
#         'gtf',
#         default_export="geotiff"
#     )
#     # tif_source = lib.ol.source.GeoTIFF.SourceInfo(
#     #     url="/static/qpe_builder/data/radar_data.tif",
#     #     min=-1.0,
#     #     max=1.0)
#     return lib.tethys.Display(
#         lib.tethys.Map(
#             lib.ol.layer.WebGLTile(title="Radar Reflectivity", opacity=0.8)(
#                 lib.ol.source.ImageStatic(
#                     url="/static/qpe_builder/data/radar_overlay.png",
#                     imageExtent=[-14470977.205671597, 2273623.3735015886, -6679726.267689361, 7360895.77546744]
#                 )
#             )
#         )
#     )

# @App.page
# def home(lib):
#     lib.register(
#         'geotiff.js@1.0.1',
#         'gtf',
#         default_export="geotiff"
#     )
#     return lib.tethys.Display(
#         lib.tethys.Map(
#             lib.ol.layer.WebGLTile(title="Radar Reflectivity", opacity=0.7)(
#                 lib.ol.source.GeoTIFF(
#                     sources=[{
#                         'url': '/static/qpe_builder/data/radar_data.tif'
#                     }]
#                 )
#             )
#         )
#     )