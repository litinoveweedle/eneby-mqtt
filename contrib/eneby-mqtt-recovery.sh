#!/bin/bash


if [ -f /run/eneby/eneby.state ]
then
    echo 'Giving up to recover eneby, executing reboot!'
    exit 1
else
    echo 'Sending email to notify about eneby-mqtt service failure.'
    echo "Subject: eneby-mqtt service is down" | sendmail -v root
    systemctl reset-failed eneby-mqtt.service
    systemctl restart eneby-mqtt.service
    exit 0
fi
