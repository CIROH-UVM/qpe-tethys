from tkinter import Image
from tethys_sdk.components import ComponentBase
import geopandas as gpd
from reactpy import html, web
from pathlib import Path
import os

file = Path(__file__).parent / "Greeting.js"
ssc = web.module_from_file("Greeting", file, fallback="")
Greeting = web.export(ssc, "Greeting")

class App(ComponentBase):
    """
    Tethys app class for QPE Builder.
    """

    name = "QPE Builder"
    description = (
        "Develop, run, and save custom workflows for generating regional Quantitative "
        "Precipitation Estimates (QPE)"
    )
    package = "qpe_builder"  # WARNING: Do not change this value
    index = "qpe_home"
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
def qpe_home(lib):
    
    ###########################################################################
    ## NOTE: This will work with Tethys 4.4.2
    ##   This code from Noah displays the radar and GeoJSON gage layers
    # resources = lib.hooks.use_resources()
    # geojson_path = resources.path.parent / "public" / "data" / "precip_gauges.geojson"
    # gauges_gdf = gpd.read_file(geojson_path)
    # # print(geojson_path)
    # geojson = gauges_gdf.to_json()


    # return lib.tethys.Display(
    #     lib.tethys.Map(center=[-10997148, 4569099], zoom=4)(
    #         lib.ol.layer.Image(options=lib.Props(title="Radar Reflectivity"))(
    #             lib.ol.source.ImageStatic(
    #                 options=lib.Props(
    #                     url="/static/qpe_builder/data/radar_overlay.png", # all data we want to disply must be in "/static/qpe_builder/data/"
    #                     imageExtent=[-14470977.205671597, 2273623.3735015886, -6679726.267689361, 7360895.77546744]
    #                 )
    #             )
    #         ),
    #         lib.ol.layer.Vector(options=lib.Props(title="Precip Gagues"))(
    #             lib.ol.source.Vector(
    #                 options=lib.Props(
    #                     features=geojson,
    #                     format="GeoJSON"
    #                 )
    #             )
    #         )
    #     )
    # )
    # #point = lib.ol.Feature(name="New York City", geometry=lib.ol.geom.Point([-8238310.235647004, 4970071.579142427]))
    # #VectorSource.addFeature(point)
    ###########################################################################
    
    
    
#    print(os.listdir('.'))
#    print(os.listdir('/'))

#    return html.div(html.p("Test"), Greeting({"name": "Noah",}))

    layer1 = (
        lib.ol.layer.Image(
                options=lib.Props(
                    title="Radar Reflectivity", opacity=0.6, visible=True
                )
            )(
            lib.ol.source.ImageStatic(
                options=lib.Props(
                    url="/static/qpe_builder/data/radar_overlay.png",
                    imageExtent=[-14470977.205671597, 2273623.3735015886, -6679726.267689361, 7360895.77546744]
                )
            )
        )
    )

    layer2 = (
        lib.ol.layer.Image(
                options=lib.Props(
                    title="Radar Reflectivity 2", opacity=0.6, visible=True
                )
            )(
            lib.ol.source.ImageStatic(
                options=lib.Props(
                    url="/static/qpe_builder/data/radar_overlay.png",
                    imageExtent=[-16470977.205671597, 2273623.3735015886, -8679726.267689361, 7360895.77546744]
                )
            )
        )
    )

    layers=[layer1]
    map_children, set_children = lib.hooks.use_state(layers)

    def button_click(e):
        print("Button Clicked")
        set_children([layer1, layer2])

### This works in 4.4.0 -- with the changes that the properties are no longer auto-exposed
    return lib.tethys.Display(
#         lib.tethys.Map(zoom=4)(
#             lib.ol.layer.Image(
# #                title="Radar Reflectivity", opacity=0.8
#                     options=lib.Props(
#                         title="Radar Reflectivity", opacity=0.6, visible=True
#                     )
#                 )(
#                 lib.ol.source.ImageStatic(
# #                    url="/static/qpe_builder/data/radar_overlay.png",
# #                    imageExtent=[-14470977.205671597, 2273623.3735015886, -6679726.267689361, 7360895.77546744]
#                     options=lib.Props(
#                         url="/static/qpe_builder/data/radar_overlay.png",
#                         imageExtent=[-14470977.205671597, 2273623.3735015886, -6679726.267689361, 7360895.77546744]
#                     )
#                 )
#             )
#         ),
        lib.tethys.Map(zoom=4, children=map_children),
        html.div({
           "style": {"position": "fixed", "top": "80%", "left": "80%", "z-index": "1000"},
        },
        lib.bs.Button(on_click=button_click)("Button"),
        ),
    )

# Changeing z-index: https://www.google.com/search?q=css+change+z+index
# Floating <div>: https://www.google.com/search?q=div+float+over+other+content

#    return html.img({"src" : "/static/qpe_builder/data/radar_overlay.png",})

#       lib.tethys.Chart()
#    ))



# # try using geotiff.js 
# @App.page(url="radar", title="Radar Reflectivity")
# def radar(lib):
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
