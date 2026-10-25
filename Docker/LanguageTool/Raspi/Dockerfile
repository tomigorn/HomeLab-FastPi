FROM erikvl87/languagetool:6.8
# lt-entrypoint.sh patches these files on every start and start.sh appends langtool_* to config.properties. Hand exactly them to the dedicated
# runtime uid; the image's own uid 100 is the host's messagebus (D-Bus) user.
USER root
RUN apk upgrade --no-cache
RUN cd /LanguageTool/org/languagetool \
 && chown 65038:65038 \
      resource/de/hunspell/spelling-de-CH.txt resource/en/hunspell/spelling_en-GB.txt \
      rules/de/grammar.xml rules/de/de-CH/grammar.xml \
      rules/en/grammar.xml rules/en/en-GB/grammar.xml \
      /LanguageTool/config.properties
USER 65038:65038
