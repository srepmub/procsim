#!/bin/sh
#-----------------------------------------------------------
# S&T procsim demo
#-----------------------------------------------------------

# Exit when any command fails
set -e

echo '  *** Generate aux data for Level 1 processor'
procsim -l debug -s "Aux generator" procsim_config_aux.json
