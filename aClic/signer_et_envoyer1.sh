#!/bin/sh

CLEF_SECRETE_TOTP='HVOAYKQY4EDZW==='
TOTP=$(./calculerTOTP  $CLEF_SECRETE_TOTP)
echo "Code d'authentification : $TOTP"

./aClic xml_entree=signer_et_envoyer.xml session_code=$TOTP
