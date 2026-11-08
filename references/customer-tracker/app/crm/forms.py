from django import forms


class CustomerCreateForm(forms.Form):
    first_name = forms.CharField(max_length=100)
    last_name = forms.CharField(max_length=100)
    email = forms.EmailField(max_length=254)
    phone = forms.CharField(max_length=40, required=False)


class ContactEditForm(forms.Form):
    email = forms.EmailField(max_length=254)
    phone = forms.CharField(max_length=40, required=False)
