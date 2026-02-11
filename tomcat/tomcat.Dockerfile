FROM tomcat:9-jre8-temurin-jammy

ENV MEM_OPTS="-Xmx500m -Xms256m"
ENV GRADLE_OPTS="-server $MEM_OPTS -XX:+UseParallelGC -XX:SoftRefLRUPolicyMSPerMB=1 -XX:MaxHeapFreeRatio=99 -Dorg.gradle.daemon=false"
ENV JAVA_OPTS="$JAVA_OPTS -Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true $MEM_OPTS -XX:+UseParallelGC -XX:SoftRefLRUPolicyMSPerMB=1 -XX:MaxHeapFreeRatio=99"

# Intermine seems to need this to deploy.
RUN cp -avT $CATALINA_HOME/webapps.dist/manager $CATALINA_HOME/webapps/manager

COPY ./configs/conf/*.xml /usr/local/tomcat/conf
COPY ./configs/webapps/manager/META-INF/context.xml /usr/local/tomcat/webapps/manager/META-INF
COPY ./configs/webapps/manager/WEB-INF/web.xml /usr/local/tomcat/webapps/manager/WEB-INF
