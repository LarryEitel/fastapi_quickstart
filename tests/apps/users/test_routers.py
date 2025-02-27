import pytest
from faker import Faker
from fastapi import FastAPI, status
from httpx import AsyncClient, Response
from pytest_mock import MockerFixture

from apps.CORE.enums import JSENDStatus, TokenAudience
from apps.CORE.managers import TokensManager
from apps.users.enums import UsersStatuses
from tests.apps.conftest import assert_jsend_response
from tests.apps.CORE.factories import UserFactory


class TestUsersRouter:
    async def test_create_user_422_no_body(self, async_client: AsyncClient, app_fixture: FastAPI) -> None:
        response = await async_client.post(url=app_fixture.url_path_for(name="create_user"))

        assert_jsend_response(
            response=response,
            http_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            status=JSENDStatus.FAIL,
            message="Validation error.",
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            data=[{"context": None, "location": ["body"], "message": "Field required.", "type": "value_error.missing"}],
        )

    async def test_create_user_200(self, async_client: AsyncClient, app_fixture: FastAPI, faker: Faker) -> None:
        email, first_name, last_name, password = faker.email(), faker.first_name(), faker.last_name(), faker.password()

        response = await async_client.post(
            url=app_fixture.url_path_for(name="create_user"),
            json={"firstName": first_name, "lastName": last_name, "email": email, "password": password},
        )

        # check response
        response_json = response.json()
        assert response.status_code == status.HTTP_201_CREATED
        assert response_json["code"] == status.HTTP_201_CREATED
        assert response_json["status"] == JSENDStatus.SUCCESS
        assert response_json["message"] == "Created User's details."
        # check "data" object.
        response_data = response_json["data"]
        assert response_data["email"] == email
        assert response_data["firstName"] == first_name
        assert response_data["lastName"] == last_name
        assert response_data["status"] == UsersStatuses.CONFIRMED
        assert response_data["groups"] == []
        assert response_data["roles"] == []
        assert response_data["permissions"] == []
        # check that these keys are exists.
        for k in ("id", "createdAt", "updatedAt"):
            assert k in response_data

        assert response_data["createdAt"] == response_data["updatedAt"]


class TestTokensRouter:
    async def test_login_422_no_body(self, async_client: AsyncClient, app_fixture: FastAPI) -> None:
        response = await async_client.post(url=app_fixture.url_path_for(name="login"))

        assert_jsend_response(
            response=response,
            http_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            status=JSENDStatus.FAIL,
            message="Validation error.",
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            data=[{"context": None, "location": ["body"], "message": "Field required.", "type": "value_error.missing"}],
        )

    async def test_login_422_fields_required(self, async_client: AsyncClient, app_fixture: FastAPI) -> None:
        response = await async_client.post(url=app_fixture.url_path_for(name="login"), json={})

        assert_jsend_response(
            response=response,
            http_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            status=JSENDStatus.FAIL,
            message="Validation error.",
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            data=[
                {
                    "location": ["body", "email"],
                    "message": "Field required.",
                    "type": "value_error.missing",
                    "context": None,
                },
                {
                    "location": ["body", "password"],
                    "message": "Field required.",
                    "type": "value_error.missing",
                    "context": None,
                },
            ],
        )

    async def test_login_400_no_user(self, async_client: AsyncClient, app_fixture: FastAPI, faker: Faker) -> None:
        response = await async_client.post(
            url=app_fixture.url_path_for(name="login"), json={"email": faker.email(), "password": faker.password()}
        )

        assert_jsend_response(
            response=response,
            http_code=status.HTTP_400_BAD_REQUEST,
            status=JSENDStatus.FAIL,
            message="Invalid credentials.",
            code=status.HTTP_400_BAD_REQUEST,
            data=None,
        )

    async def test_login_400_inactive_user(self, async_client: AsyncClient, app_fixture: FastAPI, faker: Faker) -> None:
        password = faker.pystr()
        user = UserFactory(password=password, status=UsersStatuses.UNCONFIRMED)

        response = await async_client.post(
            url=app_fixture.url_path_for(name="login"), json={"email": user.email, "password": password}
        )

        assert_jsend_response(
            response=response,
            http_code=status.HTTP_400_BAD_REQUEST,
            status=JSENDStatus.FAIL,
            message="Invalid credentials.",
            code=status.HTTP_400_BAD_REQUEST,
            data=None,
        )

    async def test_login_200(
        self, async_client: AsyncClient, app_fixture: FastAPI, faker: Faker, mocker: MockerFixture
    ) -> None:
        access, refresh = faker.pystr(), faker.pystr()
        mocker.patch.object(target=TokensManager, attribute="create_code", side_effect=(access, refresh))
        password = faker.password()
        user = UserFactory(password=password, status=UsersStatuses.CONFIRMED)

        response = await async_client.post(
            url=app_fixture.url_path_for(name="login"), json={"email": user.email, "password": password}
        )

        assert_jsend_response(
            response=response,
            http_code=status.HTTP_200_OK,
            status=JSENDStatus.SUCCESS,
            message="Tokens to authenticate user for working with API.",
            code=status.HTTP_200_OK,
            data={"accessToken": access, "refreshToken": refresh},
        )

    async def test_refresh_400_invalid(self, async_client: AsyncClient, app_fixture: FastAPI, faker: Faker) -> None:
        response = await async_client.put(
            url=app_fixture.url_path_for(name="refresh"), json={"refreshToken": faker.pystr()}
        )

        assert_jsend_response(
            response=response,
            http_code=status.HTTP_400_BAD_REQUEST,
            status=JSENDStatus.FAIL,
            message="Invalid JWT.",
            code=status.HTTP_400_BAD_REQUEST,
            data=None,
        )

    async def test_refresh_200(
        self, async_client: AsyncClient, app_fixture: FastAPI, faker: Faker, mocker: MockerFixture
    ) -> None:
        user = UserFactory(status=UsersStatuses.CONFIRMED)
        refresh_token = app_fixture.state.tokens_manager.create_code(
            data={"id": str(user.id), "token_id": 1},
            aud=TokenAudience.REFRESH,
        )
        access, refresh = faker.pystr(), faker.pystr()
        mocker.patch.object(target=TokensManager, attribute="create_code", side_effect=(access, refresh))

        response = await async_client.put(
            url=app_fixture.url_path_for(name="refresh"), json={"refreshToken": refresh_token}
        )

        assert_jsend_response(
            response=response,
            http_code=status.HTTP_200_OK,
            status=JSENDStatus.SUCCESS,
            message="Tokens to authenticate user for working with API.",
            code=status.HTTP_200_OK,
            data={"refreshToken": refresh, "accessToken": access},
        )

    @pytest.mark.parametrize(
        argnames=("user_status",), argvalues=([UsersStatuses.ARCHIVED], [UsersStatuses.UNCONFIRMED])
    )
    async def test_refresh_400_inactive(
        self, user_status: UsersStatuses, async_client: AsyncClient, app_fixture: FastAPI, faker: Faker
    ) -> None:
        user = UserFactory(status=user_status)
        refresh_token = app_fixture.state.tokens_manager.create_code(
            data={"id": str(user.id), "token_id": 1},
            aud=TokenAudience.REFRESH,
        )

        response = await async_client.put(
            url=app_fixture.url_path_for(name="refresh"), json={"refreshToken": refresh_token}
        )

        assert_jsend_response(
            response=response,
            http_code=status.HTTP_400_BAD_REQUEST,
            status=JSENDStatus.FAIL,
            message="Inactive user.",
            code=status.HTTP_400_BAD_REQUEST,
            data=None,
        )
