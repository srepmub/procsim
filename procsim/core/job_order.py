'''
Copyright (C) 2021 S[&]T, The Netherlands.

Read JobOrders, according to ESA-EOPG-EEGS-ID-0083
'''
import os
import re
import subprocess
from typing import List
from xml.etree import ElementTree as et

from procsim.core.exceptions import ProcsimException

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
JOB_ORDER_SCHEMA = os.path.join(THIS_DIR, 'job_order_ESA-EOPG-EEGS-ID-0083.xsd')


class JobOrderInput():
    '''
    Data class describing input product
    '''
    def __init__(self):
        self.id: str
        self.alternative_input_id: str
        self.file_type: str
        self.file_names: List[str] = []


class JobOrderOutput():
    '''
    Data class describing output product
    '''
    def __init__(self):
        self.type: str
        self.dir: str
        self.baseline: int
        self.file_name_pattern: str


class JobOrderIntermediateOutput():
    '''
    Data class describing an intermediate output file
    '''
    def __init__(self):
        self.id: str    # Identifier of the intermediate output. The Task’s executable shall be able to recognize it.
        self.file_name: str  #


class JobOrderTask():
    '''
    Data class with task parameters
    '''
    def __init__(self):
        self.name: str = ''
        self.version: str = ''
        self.nr_cpu_cores = 0.0     # A value of 0 means no limit
        self.amount_of_ram_mb = 1000000     # limit
        self.disk_space_mb = 1000000        # limit
        self.inputs: List[JobOrderInput] = []
        self.outputs: List[JobOrderOutput] = []
        self.intermediate_outputs: List[JobOrderIntermediateOutput] = []
        self.processing_parameters = {}


class JobOrderParser:
    '''
    This class is responsible for reading (test and parse) the JobOrder.

    Only errors are logged, since the logger is not setup yet (it needs info
    from the JobOrder for that).
    '''

    def __init__(self, logger, schema):
        self._logger = logger
        self._is_validated = False
        self._schema = schema
        self.processor_name = ''
        self.processor_version = ''

        # This flag will enable/disable any kind of breakpoint functionality
        # generation implemented by the processor
        self.intermediate_output_enable = True
        self.node = 'N/A'
        self.tasks: List[JobOrderTask] = []
        self.stdout_levels: List[str] = ['INFO', 'PROGRESS', 'WARNING', 'ERROR']
        self.stderr_levels: List[str] = []

    def read(self, filename):
        if filename is not None:
            self._check_against_schema(filename, self._schema)
            self._parse(filename)

    def _check_against_schema(self, filename, schema):
        cmd = 'xmllint --noout --schema {} {}'.format(
            schema, filename
        )
        xmllint = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        result = xmllint.stderr.decode('utf-8').strip('\n')
        if 'validates' not in result:
            self._logger.error('Check {} against {}: {}'.format(
                os.path.basename(filename),
                os.path.basename(schema),
                result
            ))
            self._is_validated = False
        else:
            self._is_validated = True

    def _find_matching_files(self, pattern):
        # Return list of all files matching 'pattern'.
        # For now, assume the path is 'fixed' and the regex does not contain slashes.
        rootdir = os.path.dirname(os.path.abspath(pattern))
        files = []
        for file in os.scandir(rootdir):
            if re.match(pattern, file.path) or os.path.abspath(pattern) == file.path:
                files.append(file.path)
        return files

    def _parse(self, filename):
        tree = et.parse(filename)
        root = tree.getroot()
        proc = root.find('Processor_Configuration')
        self.processor_name = proc.findtext('Processor_Name')
        self.processor_version = proc.findtext('Processor_Version')
        self.node = proc.findtext('Processing_Node')
        self.stdout_levels = []
        self.stderr_levels = []
        for level_el in proc.find('List_of_Stdout_Log_Levels').findall('Stdout_Log_Level'):
            self.stdout_levels.append(level_el.text or '')
        for level_el in proc.find('List_of_Stderr_Log_Levels').findall('Stderr_Log_Level'):
            self.stderr_levels.append(level_el.text or '')
        self.intermediate_output_enable = proc.findtext('Intermediate_Output_Enable') == 'true'

        # Build list of tasks
        for task_el in root.find('List_of_Tasks').findall('Task'):
            task = JobOrderTask()
            task.name = task_el.findtext('Task_Name', '')
            task.version = task_el.findtext('Task_Version', '')
            task.nr_cpu_cores = float(task_el.findtext('Number_of_CPU_Cores', '0.0'))
            task.amount_of_ram_mb = int(task_el.findtext('Amount_of_RAM', '1000000'))
            task.disk_space_mb = int(task_el.findtext('Disk_Space', '1000000'))
            task.inputs = []
            task.outputs = []
            task.intermediate_outputs = []

            for input_el in task_el.find('List_of_Inputs').findall('Input'):
                input = JobOrderInput()
                input.id = input_el.findtext('Input_ID', '')
                input.alternative_input_id = input_el.findtext('Alternative_ID', '')
                file_types_el = input_el.find('List_of_File_Types')
                input.file_type = file_types_el.findtext('File_Type', '')
                for file_name_el in file_types_el.find('List_of_File_Names').findall('File_Name'):
                    # input.file_names.append(file_name_el.text or '')

                    # HACK alert: in ICD2020, there are NO regex filenames, all file names must be fully specified!
                    # This must be patched in the PF (PVML in this case)
                    input.file_names.extend(self._find_matching_files(file_name_el.text))
                task.inputs.append(input)

            for output_el in task_el.find('List_of_Outputs').findall('Output'):
                output = JobOrderOutput()
                output.type = output_el.findtext('File_Type', '')
                output.dir = output_el.findtext('File_Dir', '')  # Can be empty or omitted
                output.baseline = int(output_el.findtext('Baseline', '0'))
                output.file_name_pattern = output_el.findtext('File_Name_Pattern', '')
                task.outputs.append(output)

            if self.intermediate_output_enable:
                for int_output_el in task_el.find('List_of_Intermediate_Outputs').findall('Intermediate_Output'):
                    int_output = JobOrderIntermediateOutput()
                    int_output.id = int_output_el.findtext('Intermediate_Output_ID', '')
                    int_output.file_name = int_output_el.findtext('Intermediate_Output_File', '')
                    task.intermediate_outputs.append(int_output)

            # List of processing parameters
            for param in task_el.find('List_of_Proc_Parameters').findall('Proc_Parameter'):
                task.processing_parameters[param.findtext('Name')] = param.findtext('Value')

            self.tasks.append(task)


def job_order_parser_factory(icd, logger):
    '''
    Return JobOrderParser. Currently only supports ICD ESA-EOPG-EEGS-ID-0083.
    '''
    if icd == 'ESA-EOPG-EEGS-ID-0083':
        return JobOrderParser(logger, JOB_ORDER_SCHEMA)
    raise ProcsimException('Unknown JobOrder ICD type {}'.format(icd))