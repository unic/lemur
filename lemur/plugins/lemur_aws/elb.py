"""
.. module: lemur.plugins.lemur_aws.elb
    :synopsis: Module contains some often used and helpful classes that
    are used to deal with ELBs

.. moduleauthor:: Kevin Glisson <kglisson@netflix.com>
"""
import botocore
from flask import current_app

from retrying import retry

from lemur.extensions import metrics, sentry
from lemur.exceptions import InvalidListener
from lemur.plugins.lemur_aws.sts import sts_client


def retry_throttled(exception):
    """
    Determines if this exception is due to throttling
    :param exception:
    :return:
    """

    # Log details about the exception
    try:
        raise exception
    except Exception as e:
        current_app.logger.error("ELB retry_throttled triggered", exc_info=True)
        metrics.send("elb_retry", "counter", 1, metric_tags={"exception": str(e)})
        sentry.captureException()

    if isinstance(exception, botocore.exceptions.ClientError):
        if exception.response["Error"]["Code"] == "LoadBalancerNotFound":
            return False

        if exception.response["Error"]["Code"] == "CertificateNotFound":
            return False
    return True


def is_valid(listener_tuple):
    """
    There are a few rules that aws has when creating listeners,
    this function ensures those rules are met before we try and create
    or update a listener.

    While these could be caught with boto exception handling, I would
    rather be nice and catch these early before we sent them out to aws.
    It also gives us an opportunity to create nice user warnings.

    This validity check should also be checked in the frontend
    but must also be enforced by server.

    :param listener_tuple:
    """
    lb_port, i_port, lb_protocol, arn = listener_tuple
    if lb_protocol.lower() in ["ssl", "https"]:
        if not arn:
            raise InvalidListener

    return listener_tuple


def get_all_elbs(**kwargs):
    """
    Fetches all elbs for a given account/region

    :param kwargs:
    :return:
    """
    elbs = []
    try:
        while True:
            response = get_elbs(**kwargs)

            elbs += response["LoadBalancerDescriptions"]

            if not response.get("NextMarker"):
                return elbs
            else:
                kwargs.update(dict(Marker=response["NextMarker"]))
    except Exception as e:  # noqa
        metrics.send("get_all_elbs_error", "counter", 1)
        sentry.captureException()
        raise


def get_all_elbs_v2(**kwargs):
    """
    Fetches all elbs for a given account/region

    :param kwargs:
    :return:
    """
    elbs = []

    try:
        while True:
            response = get_elbs_v2(**kwargs)
            elbs += response["LoadBalancers"]

            if not response.get("NextMarker"):
                return elbs
            else:
                kwargs.update(dict(Marker=response["NextMarker"]))
    except Exception as e:  # noqa
        metrics.send("get_all_elbs_v2_error", "counter", 1)
        sentry.captureException()
        raise


@sts_client("elbv2")
@retry(retry_on_exception=retry_throttled, wait_fixed=2000, stop_max_attempt_number=20)
def get_listener_arn_from_endpoint(endpoint_name, endpoint_port, **kwargs):
    """
    Get a listener ARN from an endpoint.
    :param endpoint_name:
    :param endpoint_port:
    :return:
    """
    try:
        client = kwargs.pop("client")
        elbs = client.describe_load_balancers(Names=[endpoint_name])
        for elb in elbs["LoadBalancers"]:
            listeners = client.describe_listeners(
                LoadBalancerArn=elb["LoadBalancerArn"]
            )
            for listener in listeners["Listeners"]:
                if listener["Port"] == endpoint_port:
                    return listener["ListenerArn"]
    except Exception as e:  # noqa
        metrics.send(
            "get_listener_arn_from_endpoint_error",
            "counter",
            1,
            metric_tags={
                "error": str(e),
                "endpoint_name": endpoint_name,
                "endpoint_port": endpoint_port,
            },
        )
        sentry.captureException(
            extra={
                "endpoint_name": str(endpoint_name),
                "endpoint_port": str(endpoint_port),
            }
        )
        raise


@sts_client("elb")
@retry(retry_on_exception=retry_throttled, wait_fixed=2000, stop_max_attempt_number=20)
def get_elbs(**kwargs):
    """
    Fetches one page elb objects for a given account and region.
    """
    try:
        client = kwargs.pop("client")
        return client.describe_load_balancers(**kwargs)
    except Exception as e:  # noqa
        metrics.send("get_elbs_error", "counter", 1, metric_tags={"error": str(e)})
        sentry.captureException()
        raise


@sts_client("elbv2")
@retry(retry_on_exception=retry_throttled, wait_fixed=2000, stop_max_attempt_number=20)
def get_elbs_v2(**kwargs):
    """
    Fetches one page of elb objects for a given account and region.

    :param kwargs:
    :return:
    """
    try:
        client = kwargs.pop("client")
        return client.describe_load_balancers(**kwargs)
    except Exception as e:  # noqa
        metrics.send("get_elbs_v2_error", "counter", 1, metric_tags={"error": str(e)})
        sentry.captureException()
        raise


@sts_client("elbv2")
@retry(retry_on_exception=retry_throttled, wait_fixed=2000, stop_max_attempt_number=20)
def describe_listeners_v2(**kwargs):
    """
    Fetches one page of listener objects for a given elb arn.

    :param kwargs:
    :return:
    """
    try:
        client = kwargs.pop("client")
        return client.describe_listeners(**kwargs)
    except Exception as e:  # noqa
        metrics.send(
            "describe_listeners_v2_error", "counter", 1, metric_tags={"error": str(e)}
        )
        sentry.captureException()
        raise


@sts_client("elb")
@retry(retry_on_exception=retry_throttled, wait_fixed=2000, stop_max_attempt_number=20)
def describe_load_balancer_policies(load_balancer_name, policy_names, **kwargs):
    """
    Fetching all policies currently associated with an ELB.

    :param load_balancer_name:
    :return:
    """

    try:
        return kwargs["client"].describe_load_balancer_policies(
            LoadBalancerName=load_balancer_name, PolicyNames=policy_names
        )
    except Exception as e:  # noqa
        metrics.send(
            "describe_load_balancer_policies_error",
            "counter",
            1,
            metric_tags={
                "load_balancer_name": load_balancer_name,
                "policy_names": policy_names,
                "error": str(e),
            },
        )
        sentry.captureException(
            extra={
                "load_balancer_name": str(load_balancer_name),
                "policy_names": str(policy_names),
            }
        )
        raise


@sts_client("elbv2")
@retry(retry_on_exception=retry_throttled, wait_fixed=2000, stop_max_attempt_number=20)
def describe_ssl_policies_v2(policy_names, **kwargs):
    """
    Fetching all policies currently associated with an ELB.

    :param policy_names:
    :return:
    """
    try:
        return kwargs["client"].describe_ssl_policies(Names=policy_names)
    except Exception as e:  # noqa
        metrics.send(
            "describe_ssl_policies_v2_error",
            "counter",
            1,
            metric_tags={"policy_names": policy_names, "error": str(e)},
        )
        sentry.captureException(extra={"policy_names": str(policy_names)})
        raise


@sts_client("elb")
@retry(retry_on_exception=retry_throttled, wait_fixed=2000, stop_max_attempt_number=20)
def describe_load_balancer_types(policies, **kwargs):
    """
    Describe the policies with policy details.

    :param policies:
    :return:
    """
    return kwargs["client"].describe_load_balancer_policy_types(
        PolicyTypeNames=policies
    )


@sts_client("elb")
@retry(retry_on_exception=retry_throttled, wait_fixed=2000, stop_max_attempt_number=20)
def attach_certificate(name, port, certificate_id, **kwargs):
    """
    Attaches a certificate to a listener, throws exception
    if certificate specified does not exist in a particular account.

    :param name:
    :param port:
    :param certificate_id:
    """
    try:
        return kwargs["client"].set_load_balancer_listener_ssl_certificate(
            LoadBalancerName=name,
            LoadBalancerPort=port,
            SSLCertificateId=certificate_id,
        )
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "LoadBalancerNotFound":
            current_app.logger.warning("Loadbalancer does not exist.")
        else:
            raise e


@sts_client("elbv2")
@retry(retry_on_exception=retry_throttled, wait_fixed=2000, stop_max_attempt_number=20)
def attach_certificate_v2(listener_arn, port, certificates, **kwargs):
    """
    Attaches a certificate to a listener, throws exception
    if certificate specified does not exist in a particular account.

    :param listener_arn:
    :param port:
    :param certificates:
    """
    try:
        return kwargs["client"].modify_listener(
            ListenerArn=listener_arn, Port=port, Certificates=certificates
        )
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "LoadBalancerNotFound":
            current_app.logger.warning("Loadbalancer does not exist.")
        else:
            raise e
