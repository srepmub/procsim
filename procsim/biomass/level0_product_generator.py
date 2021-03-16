'''
Copyright (C) 2021 S[&]T, The Netherlands.

Biomass Level 0 product generators,
format according to BIO-ESA-EOPG-EEGS-TN-0073

TODO: Remove all duplicated code!
'''
import bisect
import datetime
import os
from typing import List

from job_order import JobOrderInput

from biomass import (constants, main_product_header, product_generator,
                     product_name)


class Sx_RAW__0x(product_generator.ProductGeneratorBase):
    '''
    This class implements the ProductGeneratorBase and is responsible for
    generating Level-0 slice based products.

    Input is a set of (partial) RAWSxxx_10 slices.
    If one or more slices are incomplete (due to dump transitions), they are
    merged. The output is a single product, or multiple if there are data take
    transitions within the slice period.
    '''

    PRODUCTS = ['S1_RAW__0S', 'S2_RAW__0S', 'S3_RAW__0S', 'Sx_RAW__0S',
                'S1_RAWP_0M', 'S2_RAWP_0M', 'S3_RAWP_0M', 'Sx_RAWP_0M',
                'RO_RAW__0S', 'RO_RAWP_0M',
                'EC_RAWP_0M', 'EC_RAWP_0S'
                ]

    def __init__(self, logger, job_config, scenario_config: dict, output_config: dict):
        super().__init__(logger, job_config, scenario_config, output_config)

        # Get anx list from config. Can be located at either scenario or product level
        anx_list = output_config.get('anx') or scenario_config.get('anx')
        if anx_list is None:
            raise Exception('ANX must be configured for {} product'.format(self._output_type))
        self.anx_list = [self._time_from_iso(anx) for anx in anx_list]
        self.anx_list.sort()

    def parse_inputs(self, input_products: List[JobOrderInput]) -> bool:
        # First copy the metadata from any input product (normally H or V)
        if not super().parse_inputs(input_products):
            return False

        # 'Merge' partial H or V slices. If either H or V (or both?) consists of
        # multiple parts, then use the overall time as validity period for the
        # output.
        if self._output_type in [
                'S1_RAW__0S', 'S2_RAW__0S', 'S3_RAW__0S', 'Sx_RAW__0S',
                'S1_RAWP_0M', 'S2_RAWP_0M', 'S3_RAWP_0M', 'Sx_RAWP_0M']:
            hv_products = ['RAWS025_10', 'RAWS026_10']
        elif self._output_type in ['RO_RAW__0S', 'RO_RAWP_0M']:
            hv_products = ['RAWS027_10', 'RAWS028_10']
        else:
            hv_products = ['RAWS035_10', 'RAWS036_10']

        start = self.hdr._validity_start
        stop = self.hdr._validity_stop
        if start is None or stop is None:
            self._logger.error('Start and stop must be known')
            return False
        nr_hv_found = [0, 0]
        for input in input_products:
            if input.file_type in hv_products:
                for file in input.file_names:
                    file, _ = os.path.splitext(file)    # Remove possible '.zip'
                    gen = product_name.ProductName()
                    gen.parse_path(file)
                    mph_file_name = os.path.join(file, gen.generate_mph_file_name())
                    hdr = main_product_header.MainProductHeader()
                    hdr.parse(mph_file_name)
                    start = min(start, hdr._validity_start)
                    stop = max(stop, hdr._validity_stop)
                    # Diagnostics
                    idx = hv_products.index(input.file_type)
                    nr_hv_found[idx] += 1
        self.hdr._validity_start = start
        self.hdr._validity_stop = stop
        self._logger.debug('Merged {} H, V input products of type {}'.format(
            nr_hv_found, hv_products)
        )
        return True

    def _get_anx(self, t):
        # Returns the latest ANX before the given time
        idx = bisect.bisect(self.anx_list, t) - 1  # anx_list[idx-1] <= tstart
        return self.anx_list[min(max(idx, 0), len(self.anx_list) - 1)]

    def _is_incomplete_slice(self, slice_start, slice_end):
        '''
        Returns True if a slice does not start or ends on a 'node', a point on
        the grid starting from ANX.
        '''
        anx = self._get_anx(slice_start)
        SIGMA = datetime.timedelta(0, 0.1)
        rest = ((slice_start - anx + SIGMA) % constants.SLICE_GRID_SPACING)
        start_is_aligned = rest < SIGMA * 2
        rest = ((slice_end - anx + SIGMA) % constants.SLICE_GRID_SPACING)
        end_is_aligned = rest < SIGMA * 2
        if not start_is_aligned and not end_is_aligned:
            self._logger.debug('Incomplete slice, start and end unaligned to anx={}'.format(anx))
        elif not start_is_aligned:
            self._logger.debug('Incomplete slice, start unaligned to anx={}'.format(anx))
        elif not end_is_aligned:
            self._logger.debug('Incomplete slice, end unaligned to anx={}'.format(anx))
        return not start_is_aligned or not end_is_aligned

    def _generate_product(self, start, stop, data_take_config):
        if data_take_config.get('data_take_id') is None:
            raise Exception('data_take_id is mandatory in data_take section')

        for param, hdr_field, ptype in self.HDR_PARAMS:
            self._read_config_param(data_take_config, param, self.hdr, hdr_field, ptype)
        for param, acq_field, ptype in self.ACQ_PARAMS:
            self._read_config_param(data_take_config, param, self.hdr.acquisitions[0], acq_field, ptype)

        type = self._resolve_wildcard_product_type()
        self._logger.debug('Datatake {} from {} to {}'.format(self.hdr.acquisitions[0].data_take_id, start, stop))

        # Setup MPH fields
        self.hdr.set_product_type(type, self._baseline_id)
        self.hdr.set_validity_times(start, stop)
        self.hdr.incomplete_l0_slice = self._is_incomplete_slice(start, stop)
        self.hdr.partial_l0_slice = False  # TODO!

        # Create name generator and setup all fields mandatory for a level0 product.
        # TODO: Move to helper method (code is duplicated for every output!)
        name_gen = product_name.ProductName()
        acq = self.hdr.acquisitions[0]
        name_gen.file_type = type
        name_gen.start_time = start
        name_gen.stop_time = stop
        name_gen.baseline_identifier = self._baseline_id
        name_gen.set_creation_date(self._create_date)
        name_gen.mission_phase = acq.mission_phase
        name_gen.global_coverage_id = acq.global_coverage_id
        name_gen.major_cycle_id = acq.major_cycle_id
        name_gen.repeat_cycle_id = acq.repeat_cycle_id
        name_gen.track_nr = acq.track_nr
        name_gen.frame_slice_nr = acq.slice_frame_nr

        dir_name = name_gen.generate_path_name()
        self.hdr.set_product_filename(dir_name)

        # Create directory and files
        self._logger.info('Create {}'.format(dir_name))
        dir_name = os.path.join(self._output_path, dir_name)
        os.makedirs(dir_name, exist_ok=True)

        file_name = os.path.join(dir_name, name_gen.generate_mph_file_name())
        self.hdr.write(file_name)

        # H/V measurement data
        file_name = os.path.join(dir_name, name_gen.generate_binary_file_name('_rxh'))
        self._generate_bin_file(file_name, self._size_mb//2)
        file_name = os.path.join(dir_name, name_gen.generate_binary_file_name('_rxv'))
        self._generate_bin_file(file_name, self._size_mb//2)

        # Ancillary products, low rate
        file_name = os.path.join(dir_name, name_gen.generate_binary_file_name('_ia_rxh'))
        self._generate_bin_file(file_name, 0)
        file_name = os.path.join(dir_name, name_gen.generate_binary_file_name('_ia_rxv'))
        self._generate_bin_file(file_name, 0)

    def generate_output(self):
        super(Sx_RAW__0x, self).generate_output()

        self._create_date, _ = self.hdr.get_phenomenon_times()   # HACK: fill in current date?

        if self.hdr._validity_start is None or self.hdr._validity_stop is None:
            self._logger.error('Validity start/end must be known')
            return
        # Find data take(s) in this slice and create products for each segment.
        start = self.hdr._validity_start
        for dt in self._scenario_config.get('data_takes'):
            dt_start_str = dt.get('start')
            dt_stop_str = dt.get('stop')
            if dt_start_str is None or dt_stop_str is None:
                self._logger.error('data_take in config should contain start/stop elements')
                return
            dt_start = self._time_from_iso(dt_start_str)
            dt_stop = self._time_from_iso(dt_stop_str)
            if dt_start <= start <= dt_stop:  # Segment starts within this data take
                end = min(self.hdr._validity_stop, dt_stop)
                self._generate_product(start, end, dt)
                if end >= self.hdr._validity_stop:
                    break
                start = end


class Sx_RAW__0M(product_generator.ProductGeneratorBase):
    '''
    This class implements the ProductGeneratorBase and is responsible for
    generating Level0 Monitoring products.

    Input is a set of sliced monitoring products.
    The product:
    - removes overlaps between adjacent monitoring products
    - stitches the resulting products
    '''

    PRODUCTS = ['S1_RAW__0M', 'S2_RAW__0M', 'S3_RAW__0M', 'Sx_RAW__0M',
                'RO_RAW__0M', 'EC_RAW__0M', 'EC_RAW__0S']

    def parse_inputs(self, input_products: List[JobOrderInput]) -> bool:
        # Retrieves the metadata
        if not super().parse_inputs(input_products):
            return False

        # The final product should cover the complete data take.
        id = self.hdr.acquisitions[0].data_take_id
        start = self.hdr._validity_start
        stop = self.hdr._validity_stop
        if start is None or stop is None:
            self._logger.error('Start/stop must be known')
            return False
        for input in input_products:
            for file in input.file_names:
                gen = product_name.ProductName()
                gen.parse_path(file)
                # Derive mph file name from product name, parse header
                hdr = self.hdr
                mph_file_name = os.path.join(file, gen.generate_mph_file_name())
                hdr.parse(mph_file_name)
                input_id = hdr.acquisitions[0].data_take_id
                # Sanity check: do all products belong to the same data take?
                if input_id != id:
                    self._logger.warning('Data take ID {} differs from {} in {}, product ignored'.format(input_id, os.path.basename(file), id))
                    continue
                self._logger.debug('Data take id {} of {} matches'.format(input_id, os.path.basename(file)))
                start = min(start, hdr._validity_start)
                stop = max(stop, hdr._validity_stop)
        if start != self.hdr._validity_start or stop != self.hdr._validity_stop:
            self._logger.debug('Adjust validity times to {} - {}'.format(start, stop))
        self.hdr._validity_start = start
        self.hdr._validity_stop = stop
        return True

    def _generate_product(self, start, stop):
        name_gen = product_name.ProductName()

        type = self._resolve_wildcard_product_type()

        # Setup all fields mandatory for a level0 product.
        acq = self.hdr.acquisitions[0]
        name_gen.file_type = type
        name_gen.start_time = start
        name_gen.stop_time = stop
        name_gen.baseline_identifier = self._baseline_id
        name_gen.set_creation_date(self._create_date)
        name_gen.mission_phase = acq.mission_phase
        name_gen.global_coverage_id = acq.global_coverage_id
        name_gen.major_cycle_id = acq.major_cycle_id
        name_gen.repeat_cycle_id = acq.repeat_cycle_id
        name_gen.track_nr = acq.track_nr
        name_gen.frame_slice_nr = acq.slice_frame_nr

        dir_name = name_gen.generate_path_name()

        self.hdr.set_product_type(type, self._baseline_id)
        self.hdr.set_product_filename(dir_name)
        self.hdr.set_validity_times(start, stop)

        # Create directory and files
        self._logger.info('Create {}'.format(dir_name))
        dir_name = os.path.join(self._output_path, dir_name)
        os.makedirs(dir_name, exist_ok=True)

        file_name = os.path.join(dir_name, name_gen.generate_mph_file_name())
        self.hdr.write(file_name)

        # H/V measurement data
        file_name = os.path.join(dir_name, name_gen.generate_binary_file_name('_rxh'))
        self._generate_bin_file(file_name, self._size_mb//2)
        file_name = os.path.join(dir_name, name_gen.generate_binary_file_name('_rxv'))
        self._generate_bin_file(file_name, self._size_mb//2)

        # Ancillary products, low rate
        file_name = os.path.join(dir_name, name_gen.generate_binary_file_name('_ia_rxh'))
        self._generate_bin_file(file_name, 0)
        file_name = os.path.join(dir_name, name_gen.generate_binary_file_name('_ia_rxv'))
        self._generate_bin_file(file_name, 0)

    def generate_output(self):
        super().generate_output()
        self._create_date, _ = self.hdr.get_phenomenon_times()   # HACK: fill in current date?
        start = self.hdr._validity_start
        stop = self.hdr._validity_stop
        self._generate_product(start, stop)


class AC_RAW__0A(product_generator.ProductGeneratorBase):
    '''
    This class implements the ProductGeneratorBase and is responsible for
    generating Level-0 ancillary products.

    Inputs are a Sx_RAW__0M product and all RAWS022_10 belonging to the same
    data take.
    The output reads the validity times of the monitoring product and adds the
    lead/trailing margins as specified in the job order, or the defaults.
    '''

    PRODUCTS = ['AC_RAW__0A']
    DEFAULT_LEAD_MARGIN = datetime.timedelta(0, 16.0)
    DEFAULT_TRAILING_MARGIN = datetime.timedelta(0, 0)

    def __init__(self, logger, job_config, scenario_config: dict, output_config: dict):
        super().__init__(logger, job_config, scenario_config, output_config)
        # TODO: read lead time from JobOrder!
        self._lead_margin = self.DEFAULT_LEAD_MARGIN
        self._trailing_margin = self.DEFAULT_TRAILING_MARGIN

    def generate_output(self):
        super().generate_output()
        self._create_date, _ = self.hdr.get_phenomenon_times()   # HACK: fill in current date?

        start = self.hdr._validity_start - self._lead_margin
        stop = self.hdr._validity_stop + self._trailing_margin

        # Setup MPH
        self.hdr.set_product_type(self._output_type, self._baseline_id)
        self.hdr.set_validity_times(start, stop)
        self.hdr.incomplete_l0_slice = False
        self.hdr.partial_l0_slice = False

        # Setup all fields mandatory for a level0 product.
        name_gen = product_name.ProductName()
        acq = self.hdr.acquisitions[0]
        name_gen.file_type = self._output_type
        name_gen.start_time = start
        name_gen.stop_time = stop
        name_gen.baseline_identifier = self._baseline_id
        name_gen.set_creation_date(self._create_date)
        name_gen.mission_phase = acq.mission_phase
        name_gen.global_coverage_id = acq.global_coverage_id
        name_gen.major_cycle_id = acq.major_cycle_id
        name_gen.repeat_cycle_id = acq.repeat_cycle_id
        name_gen.track_nr = acq.track_nr
        name_gen.frame_slice_nr = acq.slice_frame_nr

        dir_name = name_gen.generate_path_name()
        self.hdr.set_product_filename(dir_name)

        # Create directory and files
        self._logger.info('Create {}'.format(dir_name))
        dir_name = os.path.join(self._output_path, dir_name)
        os.makedirs(dir_name, exist_ok=True)

        file_name = os.path.join(dir_name, name_gen.generate_mph_file_name())
        self.hdr.write(file_name)
        file_name = os.path.join(dir_name, name_gen.generate_binary_file_name())  # TODO: SUFFIX?!
        self._generate_bin_file(file_name, self._size_mb)


class Aux(product_generator.ProductGeneratorBase):
    '''
    This class implements the ProductGeneratorBase and is responsible for
    generating Level-0 Auxiliary products.
    '''

    PRODUCTS = ['AUX_ATT___', 'AUX_ORB___']

    def generate_output(self):
        super().generate_output()
        self._create_date, _ = self.hdr.get_phenomenon_times()   # HACK: fill in current date?

        # Setup MPH
        self.hdr.set_product_type(self._output_type, self._baseline_id)

        # TODO: What other MPH fields should be set for AUX?

        # Setup all fields mandatory for an auxiliary product.
        name_gen = product_name.ProductName()
        acq = self.hdr.acquisitions[0]
        name_gen.file_type = self._output_type
        name_gen.start_time = self.hdr._validity_start
        name_gen.stop_time = self.hdr._validity_stop
        name_gen.baseline_identifier = self._baseline_id
        name_gen.set_creation_date(self._create_date)
        name_gen.mission_phase = acq.mission_phase
        name_gen.global_coverage_id = acq.global_coverage_id
        name_gen.major_cycle_id = acq.major_cycle_id
        name_gen.repeat_cycle_id = acq.repeat_cycle_id
        name_gen.track_nr = acq.track_nr
        name_gen.frame_slice_nr = acq.slice_frame_nr

        dir_name = name_gen.generate_path_name()
        self.hdr.set_product_filename(dir_name)

        # Create directories and files
        self._logger.info('Create {}'.format(dir_name))
        dir_name = os.path.join(self._output_path, dir_name)
        os.makedirs(dir_name, exist_ok=True)

        file_name = os.path.join(dir_name, name_gen.generate_mph_file_name())
        self.hdr.write(file_name)
        data_dir = os.path.join(dir_name, 'data')
        support_dir = os.path.join(dir_name, 'support')

        os.makedirs(data_dir, exist_ok=True)
        file_name = os.path.join(data_dir, name_gen.generate_binary_file_name('_attitude', '.xml'))
        self._generate_bin_file(file_name, self._size_mb // 2)

        # This component has to be considered optional because
        # it shall not be used in case AUX data format is not XML
        os.makedirs(support_dir, exist_ok=True)
        file_name = os.path.join(support_dir, name_gen.generate_binary_file_name('_schema', '.xsd'))
        self._generate_bin_file(file_name, self._size_mb // 2)
