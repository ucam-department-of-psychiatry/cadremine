# cadremine

Intermine instance for the CADRE project.

This replaces https://github.com/ucam-department-of-psychiatry/camCHILDMine (the
Intermine instance for the FAIR TREATMENT demo).

## Developer's Guide

Install Tomcat 9 somewhere where you can write to the webapps directory.

Check out Intermine (e.g.):

    $ cd ${HOME}/workspace
    $ git clone https://github.com/intermine/intermine.git

Create or append these lines to `${HOME}/.gradle/gradle.properties`, replacing /home/user/workspace as necessary:

    intermine.plugin.repo=file:///home/user/workspace/intermine/plugin/build/libs
    intermine.development.intermineRootDir=/home/user/workspace/intermine/intermine
    intermine.development.intermineModules=api,integrate,jbrowse-endpoint,model,objectstore,pathquery,resources,testresources,webapp,webtasks
    intermine.development.bioRootDir=/home/user/workspace/intermine/bio
    intermine.development.bioModules=core,model,tools,webapp,postprocess/create-attribute-indexes,postprocess/create-autocomplete-index,postprocess/create-chromosome-locations,postprocess/create-gene-flanking-features,postprocess/create-intergenic-region-features,postprocess/create-intron-features,postprocess/create-location-overlap-index,postprocess/create-overlap-view,postprocess/create-R2RML-mapping,postprocess/create-references,postprocess/create-search-index,postprocess/create-utr-references,postprocess/make-spanning-locations,postprocess/populate-child-features,postprocess/summarise-objectstore,postprocess/transfer-sequences

Create the intermine-bio WAR file:

    $ python3 -m venv ~/.virtualenvs/intermine-ci
    $ source ~/.virtualenvs/intermine-ci/bin/activate
    $ cd intermine/config/ci
    $ ./init-solr.sh ~/workspace/intermine
    $ ./init.sh ~/workspace/intermine $(which python) bio none http://localhost:8080/intermine-demo
    $ ./run.sh ~/workspace/intermine $(which python) bio none http://localhost:8080/intermine-demo

Check out cadremine:

    $ cd ${HOME}/workspace
    $ git clone https://github.com/ucam-department-of-psychiatry/cadremine.git

Create the cadremine WAR file:

    $ ./gradlew :webapp:war
    $ cp webapp/build/libs/webapp.war /path/to/tomcat9/webapps/cadremine.war

Start Tomcat:

    $ export JPDA_ADDRESS=8180  # Or whichever free port you want to use
    $ export JPDA_TRANSPORT=dt_socket
    $ ./catalina.sh jdpa start

Install Eclipse no later than 2020-03 for Java 8 support.

**File** -> **Import...** -> **Gradle** -> **Existing Gradle Project**

Select the cadremine project.


Connect to remote application:
