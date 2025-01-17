import mimetypes
import os
from datetime import datetime
from itertools import chain

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import (EmptyPage, InvalidPage, PageNotAnInteger,
                                   Paginator)
from django.http import (Http404, HttpResponse, HttpResponsePermanentRedirect,
                         JsonResponse)
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from icalendar import Calendar
from wagtail.admin import messages
from wagtail.search.backends import database, get_search_backend
from wagtail.search.models import Query

from coderedcms import utils
from coderedcms.forms import SearchForm
from coderedcms.importexport import (ImportPagesFromCSVFileForm,
                                     convert_csv_to_json, import_pages)
from coderedcms.models import (CoderedEventPage, CoderedPage, GeneralSettings,
                               LayoutSettings, get_page_models)
from coderedcms.settings import crx_settings


def search(request):
    """
    Searches pages across the entire site.
    """
    search_form = SearchForm(request.GET)
    pagetypes = []
    results = None
    results_paginated = None

    if search_form.is_valid():
        search_query = search_form.cleaned_data['s']
        search_model = search_form.cleaned_data['t']

        # get all codered models
        pagemodels = sorted(get_page_models(), key=lambda k: k.search_name)
        # get filterable models
        for model in pagemodels:
            if model.search_filterable:
                pagetypes.append(model)

        # get backend
        backend = get_search_backend()

        # DB search. Since this backend can't handle inheritance or scoring,
        # search specified page types in the desired order and chain the results together.
        # This provides better search results than simply searching limited fields on CoderedPage.
        db_models = []
        if backend.__class__ == database.SearchBackend:
            for model in get_page_models():
                if model.search_db_include:
                    db_models.append(model)
            db_models = sorted(db_models, reverse=True, key=lambda k: k.search_db_boost)

        if backend.__class__ == database.SearchBackend and db_models:
            for model in db_models:
                # if search_model is provided, only search on that model
                if not search_model or search_model == ContentType.objects.get_for_model(model).model:  # noqa
                    curr_results = model.objects.live().search(search_query)
                    if results:
                        results = list(chain(results, curr_results))
                    else:
                        results = curr_results

        # Fallback for any other search backend
        else:
            if search_model:
                try:
                    model = ContentType.objects.get(model=search_model).model_class()
                    results = model.objects.live().search(search_query)
                except ContentType.DoesNotExist:
                    results = None
            else:
                results = CoderedPage.objects.live().order_by('-last_published_at').search(search_query)  # noqa

        # paginate results
        if results:
            paginator = Paginator(results, GeneralSettings.for_request(request).search_num_results)
            page = request.GET.get('p', 1)
            try:
                results_paginated = paginator.page(page)
            except PageNotAnInteger:
                results_paginated = paginator.page(1)
            except EmptyPage:
                results_paginated = paginator.page(1)
            except InvalidPage:
                results_paginated = paginator.page(1)

        # Log the query so Wagtail can suggest promoted results
        Query.get(search_query).add_hit()

    # Render template
    return render(request, 'coderedcms/pages/search.html', {
        'request': request,
        'pagetypes': pagetypes,
        'form': search_form,
        'results': results,
        'results_paginated': results_paginated
    })


@login_required
def serve_protected_file(request, path):
    """
    Function that serves protected files uploaded from forms.
    """
    # Fully resolve all provided paths.
    mediapath = os.path.abspath(crx_settings.CRX_PROTECTED_MEDIA_ROOT)
    fullpath = os.path.abspath(os.path.join(mediapath, path))

    # Path must be a sub-path of the PROTECTED_MEDIA_ROOT, and exist.
    if fullpath.startswith(mediapath) and os.path.isfile(fullpath):
        mimetype, encoding = mimetypes.guess_type(fullpath)
        with open(fullpath, 'rb') as f:
            response = HttpResponse(f.read(), content_type=mimetype)
        if encoding:
            response["Content-Encoding"] = encoding

        return response
    raise Http404()


def favicon(request):
    icon = LayoutSettings.for_request(request).favicon
    if icon:
        return HttpResponsePermanentRedirect(icon.get_rendition('original').url)
    raise Http404()


def robots(request):
    return render(
        request,
        'robots.txt',
        content_type='text/plain'
    )


def event_generate_single_ical_for_event(request):
    if request.method == "POST":
        event_pk = request.POST['event_pk']
        event_page_models = CoderedEventPage.__subclasses__()
        dt_start_str = utils.fix_ical_datetime_format(request.POST['datetime_start'])
        dt_end_str = utils.fix_ical_datetime_format(request.POST['datetime_end'])

        dt_start = datetime.strptime(dt_start_str, "%Y-%m-%dT%H:%M:%S%z") if dt_start_str else None
        dt_end = datetime.strptime(dt_end_str, "%Y-%m-%dT%H:%M:%S%z") if dt_end_str else None
        for event_page_model in event_page_models:
            try:
                event = event_page_model.objects.get(pk=event_pk)
                break
            except event_page_model.DoesNotExist:
                pass
        ical = Calendar()
        ical.add_component(event.create_single_ical(dt_start=dt_start, dt_end=dt_end))
        response = HttpResponse(ical.to_ical(), content_type="text/calendar")
        response['Filename'] = "{0}.ics".format(event.slug)
        response['Content-Disposition'] = 'attachment; filename={0}.ics'.format(event.slug)
        return response
    raise Http404()


def event_generate_recurring_ical_for_event(request):
    if request.method == "POST":
        event_pk = request.POST['event_pk']
        event_page_models = CoderedEventPage.__subclasses__()
        for event_page_model in event_page_models:
            try:
                event = event_page_model.objects.get(pk=event_pk)
                break
            except event_page_model.DoesNotExist:
                pass
        ical = Calendar()
        for e in event.create_recurring_ical():
            ical.add_component(e)
        response = HttpResponse(ical.to_ical(), content_type="text/calendar")
        response['Filename'] = "{0}.ics".format(event.slug)
        response['Content-Disposition'] = 'attachment; filename={0}.ics'.format(event.slug)
        return response
    raise Http404()


def event_generate_ical_for_calendar(request):
    if request.method == "POST":
        try:
            page = CoderedPage.objects.get(id=request.POST.get('page_id')).specific
        except ValueError:
            raise Http404

        ical = Calendar()
        for event_page in page.get_index_children():
            for e in event_page.specific.create_recurring_ical():
                ical.add_component(e)
        response = HttpResponse(ical.to_ical(), content_type="text/calendar")
        response['Filename'] = "calendar.ics"
        response['Content-Disposition'] = 'attachment; filename=calendar.ics'
        return response
    raise Http404()


def event_get_calendar_events(request):
    """
    JSON list of events compatible with fullcalendar.js
    """
    try:
        page = CoderedPage.objects.get(id=request.GET.get('pid')).specific
    except ValueError:
        raise Http404
    start = None
    end = None
    start_str = request.GET.get('start', None)
    end_str = request.GET.get('end', None)
    if start_str:
        start = timezone.make_aware(
            datetime.strptime(start_str[:10], "%Y-%m-%d"),
        )
    if end_str:
        end = timezone.make_aware(
            datetime.strptime(end_str[:10], "%Y-%m-%d"),
        )
    return JsonResponse(
        page.get_calendar_events(start=start, end=end),
        safe=False
    )


@login_required
def import_index(request):
    """
    Landing page to replace wagtailimportexport.
    """
    return render(request, 'wagtailimportexport/index.html')


@login_required
def import_pages_from_csv_file(request):
    """
    Overwrite of the `import_pages` view from wagtailimportexport.  By default, the `import_pages`
    view expects a json file to be uploaded.  This view converts the uploaded csv into the json
    format that the importer expects.
    """

    if request.method == 'POST':
        form = ImportPagesFromCSVFileForm(request.POST, request.FILES)
        if form.is_valid():
            import_data = convert_csv_to_json(
                form.cleaned_data['file'].read().decode('utf-8').splitlines(),
                form.cleaned_data['page_type']
            )
            parent_page = form.cleaned_data['parent_page']
            try:
                page_count = import_pages(import_data, parent_page)
            except LookupError as e:
                messages.error(request, _(
                    "Import failed: %(reason)s") % {'reason': e}
                )
            else:
                messages.success(request, ngettext(
                    "%(count)s page imported.",
                    "%(count)s pages imported.",
                    page_count) % {'count': page_count}
                )
            return redirect('wagtailadmin_explore', parent_page.pk)
    else:
        form = ImportPagesFromCSVFileForm()

    return render(request, 'wagtailimportexport/import_from_csv.html', {
        'form': form,
    })
