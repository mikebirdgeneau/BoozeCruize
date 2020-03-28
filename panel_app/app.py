import sys

import requests

sys.path.insert(0, '.')
import random
from typing import List, Dict
import pandas as pd
import numpy as np
import panel as pn
import panel.widgets as pnw
import param
import altair as alt
import logging
from panel_app.maps_url import build_map_url, concat_latlongs, rearrange_waypoints, construct_gmaps_urls
from panel_app.default_dest import DEFAULT_DEST
from panel_app.here_service_utils import _geocode_destination_here, _pull_lat_long_here, _pull_address_here

alt.data_transformers.disable_max_rows()
pn.extension("vega")
DEV_BUCKET = "abiryukov"
FRAC = 0.5
WIDTH_DEFAULT = 1000
HEIGHT_DEFAULT = 150
N_RANDOM_DAYS = 7

# TODO Pull TOMTOM-specific stuff into a separate file
API_KEY_TOMTOM = '***REMOVED***'
base_url = 'https://api.tomtom.com/routing/1/calculateRoute'
start = (51.0480293, -114.0640164)
end = start

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


def default_altair(lines=False):
    data = pd.DataFrame({"x": np.random.randn(100), "y": np.random.randn(100)})
    if lines:
        ch = (
            alt.Chart(data=data, width=WIDTH_DEFAULT, height=HEIGHT_DEFAULT)
                .encode(x="x", y="y")
                .mark_line()
        )
    else:
        ch = (
            alt.Chart(data=data, width=WIDTH_DEFAULT, height=HEIGHT_DEFAULT)
                .encode(x="x", y="y")
                .mark_point()
        )

    return ch

def autocompleteCallback(inputText=''):
    # input text through automplete library to generate autocomplete results
    return

def generateAutocompleteWidget(destination_number=1):
    autocomplete = pn.widgets.AutocompleteInput(
        name=f'Destination {destination_number}', options=['Biology', 'Chemistry', 'Physics'],
        min_characters=2, placeholder='Enter Location')
    return autocomplete

def _pull_value_wlist(widget):
    return widget.value


def create_destination_inputs(n=2, prev_destinations=None, init_vals=None):
    if init_vals is not None:
        assert len(init_vals) == n
    else:
        init_vals = [""] * n

    if prev_destinations is None:
        wlist = []
        for i in range(n):
            wlist.append(generateAutocompleteWidget(i))
    else:
        wlist = prev_destinations
        n_old = len(prev_destinations)
        print(f"Nold: {n_old} , new: {n}")

        if n > n_old:
            for i in range(n_old + 1, n):
                wlist.append(generateAutocompleteWidget(i))
        else:
            wlist = wlist[0:n]

    widget_all = pn.Column(*wlist)
    return widget_all, wlist


class ReactiveForecastDashboard(param.Parameterized):
    title = pn.pane.Markdown("# Booze Cruise YYC")
    # Add a widget that picks the environment and bucket
    number_dest = param.Integer(
        8, label="Select number of destinations", bounds=(0, 15)
    )
    waypoints_per_batch = param.Integer(
        10, label="Wapoints per batch in Google Maps URL", bounds=(1, 10)
    )

    progress_bar = pnw.misc.Progress(
        active=False,
        bar_color="light",
        value=None,
        width_policy="max",
        sizing_mode="stretch_width",
    )

    date_custom_map: Dict = {}
    get_locations_action = pnw.Button(name="Get Locations", button_type="primary")
    get_best_route_action = pnw.Button(name="Get Best Route", button_type="default")
    destinations_pane, destinations_wlist = create_destination_inputs(
        n=8, prev_destinations=None, init_vals=DEFAULT_DEST
    )
    destinations_latlongs = param.List(default=[(0, 0), (0, 0)], precedence=-0.5)
    gmaps_urls = param.List(default=['', ''], precedence=-0.5)

    destinations_addresses = param.List(default=[(0, 0), (0, 0)], precedence=-0.5)
    all_dates_forecast = default_altair()
    default_plot = pn.Pane(default_altair())
    tmp_buffer = 'Temporary buffer'

    @param.depends("number_dest", watch=True)
    def change_destinations_number(self):
        new_destinations = create_destination_inputs(
            n=self.number_dest, prev_destinations=self.destinations_wlist
        )
        self.destinations_pane, self.destinations_wlist = (
            new_destinations[0],
            new_destinations[1],
        )
        return self.destinations_pane

    def geocode_dest_list_latlong(self, event, destinations_list):
        self.progress_bar.bar_color = 'info'
        self.progress_bar.active = True

        log.info(event)
        destinations_str = [_pull_value_wlist(x) for x in destinations_list]
        log.info(f"Geocoding the destinations list: {destinations_str}")
        destinations_jsons = [_geocode_destination_here(x) for x in destinations_str]
        latlongs = [_pull_lat_long_here(x, n_entry=0) for x in destinations_jsons]
        addresses = [_pull_address_here(x, n_entry=0) for x in destinations_jsons]

        log.info(latlongs)
        log.info(addresses)

        # latlongs = [(random.randint(i, 20), random.randint(i, 40)) for i in range(len(destinations_list))]
        self.destinations_latlongs = latlongs
        self.destinations_addresses = addresses
        log.info(self.destinations_latlongs)
        log.info(self.destinations_addresses)

        self.progress_bar.bar_color = 'light'
        self.progress_bar.active = False

    @param.depends('destinations_latlongs')
    def show_latlongs(self):
        destinations_str = [_pull_value_wlist(x) for x in self.destinations_wlist]

        x = f' Length = {len(self.destinations_wlist)}, vals = {destinations_str}'
        x += f' Latlongs = {len(self.destinations_latlongs)}, vals = {self.destinations_addresses}'

        res_md = pn.pane.Markdown(x)
        return res_md

    def find_best_route(self, event, latlong_list):
        '''
        Find optimal route using TomTom routing service
        :param event:
        :param latlong_list:
        :return:
        '''
        latlongs = [start] + latlong_list + [end]
        latlong_concat = concat_latlongs(latlongs)

        url_locations = f'{base_url}/{latlong_concat}/json'
        params = {'key': API_KEY_TOMTOM,
                  'travelMode': 'car',
                  'computeBestOrder': 'true',
                  'traffic': 'true',
                  'instructionsType': 'text',
                  'computeTravelTimeFor': 'all',
                  }
        response = requests.get(url_locations, params=params)
        response_json = response.json()
        latlongs_original_optimal = rearrange_waypoints(response_json)
        latlongs_optimal = [start] + latlongs_original_optimal + [end]
        _, urls = construct_gmaps_urls(latlongs_optimal, waypoints_batch_size=10)
        self.gmaps_urls = urls

    @param.depends('gmaps_urls')
    def show_urls(self):
        base_url_string = """
        ### The route links for navigation in Google Maps:
        
        URL
        """
        urls_links_md = [f'**[Group {i}]({u})**' for i, u in enumerate(self.gmaps_urls)]
        url_string = '/n/n'.join(urls_links_md)
        base_url_string = base_url_string.replace('URL', url_string)
        res_md = pn.pane.Markdown(base_url_string)
        print(res_md)
        return res_md

    def panel(self):
        # Attach a callback to geocoding button
        self.get_locations_action.on_click(
            lambda x: self.geocode_dest_list_latlong(x, destinations_list=self.destinations_wlist))
        # Attach a callback to optimal route search
        self.get_best_route_action.on_click(
            lambda x: self.find_best_route(x, latlong_list=self.destinations_latlongs))

        widgets_ = self.param
        buttons_ = pn.Column(self.get_locations_action, self.get_best_route_action)
        progress_bar = pn.Pane(
            self.progress_bar, sizing_mode="stretch_width", width_policy="max"
        )

        result = pn.Row(
            pn.Column(
                self.title,
                widgets_,
                buttons_,
                self.change_destinations_number,
                progress_bar,
            ),
            pn.Column(
                self.show_latlongs,
                self.default_plot,
                self.show_urls,
                sizing_mode="stretch_width", width_policy="max"
            ),
            sizing_mode="stretch_width",
        )
        return result


res = ReactiveForecastDashboard(name="").panel()
res.servable()
