from .entity_view import EntityView


class ModuleView(EntityView):
    def __init__(self, parent=None):
        super().__init__('modules', parent)
