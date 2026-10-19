from .entity_view import EntityView


class OperatorView(EntityView):
    def __init__(self, parent=None):
        super().__init__('operators', parent)
