import uuid
from django.db import models


class DataLayer(models.Model):
    """
    Abstract base class for all data layers in the NGPE platform.

    RasterData and PointData both extend this class.
    __data is stored privately in subclasses -- DataLayer is immutable after creation.
    creator and parents provide full traceability of every correction made.
    """

    # Primary key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Core fields
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    time_created = models.DateTimeField(auto_now_add=True)
    ref_datetime = models.DateTimeField()
    region = models.CharField(max_length=100)
    creator_tool = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict)

    # Parents -- traceability chain
    parents = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='children'
    )

    class Meta:
        abstract = True
        app_label = 'ngpe'
        ordering = ['-time_created']

    def __str__(self):
        ref_dt = self.ref_datetime
        if hasattr(ref_dt, 'strftime'):
            return f'{self.name} ({self.region} @ {ref_dt:%Y-%m-%d %H:%M})'
        return f'{self.name} ({self.region} @ {ref_dt})'

    # Abstract methods -- subclasses MUST implement these

    def to_map_layer(self) -> dict:
        """Convert backend data to an OpenLayers layer config dict."""
        raise NotImplementedError(
            f'{self.__class__.__name__} must implement to_map_layer()'
        )

    def get_data(self):
        """Return the raw data object."""
        raise NotImplementedError(
            f'{self.__class__.__name__} must implement get_data()'
        )

    def to_catalog_entry(self) -> dict:
        """Return a JSON-serialisable summary for the dropdown."""
        # ref_datetime may be a string (from HTML input) or a datetime object
        ref_dt = self.ref_datetime
        if hasattr(ref_dt, 'isoformat'):
            ref_dt = ref_dt.isoformat()
        return {
            'id': str(self.id),
            'name': self.name,
            'description': self.description,
            'region': self.region,
            'ref_datetime': str(ref_dt),
            'layer_type': self.__class__.__name__,
            'metadata': self.metadata,
        }
