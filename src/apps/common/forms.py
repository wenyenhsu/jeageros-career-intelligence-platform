from django import forms


class BootstrapFormMixin:
    """Apply Bootstrap-friendly widget classes to Django forms."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            existing = widget.attrs.get('class', '')
            classes = set(existing.split()) if existing else set()

            if isinstance(widget, forms.CheckboxInput):
                classes.discard('form-control')
                classes.discard('form-select')
                classes.add('form-check-input')
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                classes.discard('form-control')
                classes.add('form-select')
            else:
                classes.discard('form-select')
                classes.add('form-control')

            widget.attrs['class'] = ' '.join(sorted(classes))

            if isinstance(widget, forms.Textarea) and 'rows' not in widget.attrs:
                widget.attrs['rows'] = 4
