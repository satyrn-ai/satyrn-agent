from django import forms


class CustomerCreateForm(forms.Form):
    first_name = forms.CharField(max_length=100)
    last_name = forms.CharField(max_length=100)
    email = forms.EmailField(max_length=254)
    phone = forms.CharField(max_length=40, required=False)


class ContactEditForm(forms.Form):
    email = forms.EmailField(max_length=254)
    phone = forms.CharField(max_length=40, required=False)


class FollowUpCreateForm(forms.Form):
    summary = forms.CharField(max_length=200)
    due_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
    )
