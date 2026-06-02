import os
import shutil
import tempfile
import uuid
import datetime
from django.test import override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from files.models import User, File, Collection, CollectionFile, ProjectThread
from administration.models import Designation


# Create a temporary directory for MEDIA_ROOT during tests to avoid clogging
# up the real media files on the filesystem.
TEMP_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class RapidRiseAPITestCase(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create common designations for our test users
        cls.designation_a = Designation.objects.create(name="Software Engineer")
        cls.designation_b = Designation.objects.create(name="Product Manager")

    @classmethod
    def tearDownClass(cls):
        # Clean up temporary media directory
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        # Create a default test user
        self.user_password = "Password123!"
        self.user = User.objects.create_user(
            email="testuser@example.com",
            first_name="John",
            last_name="Doe",
            date_of_birth=datetime.date(1995, 5, 5),
            designation=self.designation_a,
            password=self.user_password
        )
        # Verify and make sure user is active
        self.user.account_status = User.AccountStatus.ACTIVE
        self.user.save()

    def login_user(self, email, password):
        """Helper to log in a user and set cookies/credentials."""
        url = reverse("files:login")
        response = self.client.post(url, {"email": email, "password": password})
        if response.status_code == status.HTTP_200_OK:
            # SimpleJWT tokens might be stored in cookies. Let's inspect cookies
            access_token = response.cookies.get("access_token")
            if access_token:
                self.client.cookies["access_token"] = access_token.value
        return response

    def authenticate_user(self):
        """Helper to force authenticate the user using APIClient."""
        self.client.force_authenticate(user=self.user)


class UserAuthTestCase(RapidRiseAPITestCase):
    """
    Test suite for User Authentication, covering:
    - User Registration (Success and Validation Failures)
    - User Login (Success and Wrong Credentials/Validation Failures)
    """

    def test_register_user_success(self):
        url = reverse("files:register")
        payload = {
            "email": "newuser@example.com",
            "first_name": "New",
            "last_name": "User",
            "date_of_birth": "2000-01-01",
            "designation": self.designation_b.id,
            "password": "StrongPassword123!",
            "confirm_password": "StrongPassword123!"
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["message"], "User Registered successfully!!!")
        self.assertTrue(User.objects.filter(email="newuser@example.com").exists())

    def test_register_user_validation_failures(self):
        url = reverse("files:register")

        # Case 1: Under 18 years old date of birth
        underage_dob = (datetime.date.today() - datetime.timedelta(days=10*365)).strftime("%Y-%m-%d")
        payload = {
            "email": "underage@example.com",
            "first_name": "Under",
            "last_name": "Age",
            "date_of_birth": underage_dob,
            "designation": self.designation_b.id,
            "password": "StrongPassword123!",
            "confirm_password": "StrongPassword123!"
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date_of_birth", response.data)

        # Case 2: Passwords mismatch
        payload = {
            "email": "mismatch@example.com",
            "first_name": "Password",
            "last_name": "Mismatch",
            "date_of_birth": "1998-05-12",
            "designation": self.designation_b.id,
            "password": "StrongPassword123!",
            "confirm_password": "DifferentPassword123!"
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirm_password", response.data)

        # Case 3: Invalid email format
        payload = {
            "email": "invalidemail",
            "first_name": "Invalid",
            "last_name": "Email",
            "date_of_birth": "1998-05-12",
            "designation": self.designation_b.id,
            "password": "StrongPassword123!",
            "confirm_password": "StrongPassword123!"
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_login_success(self):
        url = reverse("files:login")
        payload = {
            "email": "testuser@example.com",
            "password": self.user_password
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Login successful")
        self.assertIn("user", response.data)
        self.assertIn("access_token", response.cookies)

    def test_login_wrong_credentials(self):
        url = reverse("files:login")

        # Case 1: Wrong password
        payload = {
            "email": "testuser@example.com",
            "password": "WrongPassword123!"
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

        # Case 2: Wrong email (email does not exist)
        payload = {
            "email": "nonexistent@example.com",
            "password": self.user_password
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)


class UserProfileTestCase(RapidRiseAPITestCase):
    """
    Test suite for User Profile, covering:
    - Reading User Profile (GET)
    - Editing User Profile (PATCH) and validation checks
    """

    def setUp(self):
        super().setUp()
        self.authenticate_user()

    def test_get_profile(self):
        url = reverse("files:user-profile")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.user.email)
        self.assertEqual(response.data["first_name"], self.user.first_name)
        self.assertEqual(response.data["last_name"], self.user.last_name)

    def test_update_profile_success(self):
        url = reverse("files:user-profile")
        payload = {
            "first_name": "UpdatedJohn",
            "last_name": "UpdatedDoe",
            "date_of_birth": "1994-04-04"
        }
        response = self.client.patch(url, payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["first_name"], "UpdatedJohn")
        self.assertEqual(response.data["last_name"], "UpdatedDoe")
        self.assertEqual(response.data["date_of_birth"], "1994-04-04")

        # Verify DB changes
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "UpdatedJohn")
        self.assertEqual(self.user.last_name, "UpdatedDoe")

    def test_update_profile_validation_failures(self):
        url = reverse("files:user-profile")

        # Case 1: First name with spaces only
        payload = {"first_name": "   "}
        response = self.client.patch(url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("first_name", response.data)

        # Case 2: First name containing numbers
        payload = {"first_name": "John123"}
        response = self.client.patch(url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("first_name", response.data)

        # Case 3: Date of birth in the future
        future_dob = (datetime.date.today() + datetime.timedelta(days=10)).strftime("%Y-%m-%d")
        payload = {"date_of_birth": future_dob}
        response = self.client.patch(url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date_of_birth", response.data)


class FilesCRUDTestCase(RapidRiseAPITestCase):
    """
    Test suite for Files CRUD operations, covering:
    - Add (Upload via ChunkUploadView)
    - Read (Detail and Listing)
    - Update metadata (display_name, description)
    - Delete (Soft Delete)
    """

    def setUp(self):
        super().setUp()
        self.authenticate_user()

    def test_add_file_via_chunk_upload_success(self):
        url = reverse("files:chunk-upload")
        upload_id = str(uuid.uuid4()).replace("-", "")
        file_content = b"This is a dummy file content for testing chunk upload functionality."
        dummy_file = SimpleUploadedFile("test_document.txt", file_content, content_type="text/plain")

        payload = {
            "upload_id": upload_id,
            "chunk_index": 0,
            "total_chunks": 1,
            "file_name": "test_document.txt",
            "file_size": len(file_content),
            "content_type": "text/plain",
            "file": dummy_file,
            "description": "A wonderful test text file."
        }

        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["message"], "Chunk 0 received")
        self.assertIn("file", response.data)
        file_id = response.data["file"]["id"]
        self.assertTrue(File.objects.filter(id=file_id).exists())

    def test_file_read_update_delete(self):
        # Let's manually create a File record in database first so we can perform RUD
        file_content = b"Some test data"
        dummy_file = SimpleUploadedFile("rud_test.txt", file_content, content_type="text/plain")
        
        test_file = File.objects.create(
            user=self.user,
            file=dummy_file,
            original_name="rud_test.txt",
            file_size=len(file_content),
            content_type="text/plain",
            checksum="dummy_checksum_123",
            description="Original description"
        )

        # 1. READ Detail
        detail_url = reverse("files:file-detail", kwargs={"pk": test_file.id})
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["original_name"], "rud_test.txt")
        self.assertEqual(response.data["description"], "Original description")

        # 2. READ List
        list_url = reverse("files:file-list")
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 1)

        # 3. UPDATE
        update_url = reverse("files:file-update", kwargs={"pk": test_file.id})
        update_payload = {
            "display_name": "Beautiful Document",
            "description": "Updated description text"
        }
        response = self.client.patch(update_url, update_payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["display_name"], "Beautiful Document")
        self.assertEqual(response.data["description"], "Updated description text")

        # Verify DB update
        test_file.refresh_from_db()
        self.assertEqual(test_file.display_name, "Beautiful Document")
        self.assertEqual(test_file.description, "Updated description text")

        # 4. DELETE (Soft delete)
        delete_url = reverse("files:file-delete", kwargs={"file_id": test_file.id})
        response = self.client.delete(delete_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify it is soft-deleted
        test_file.refresh_from_db()
        self.assertTrue(test_file.is_deleted)


class CollectionsCRUDTestCase(RapidRiseAPITestCase):
    """
    Test suite for Collections CRUD operations, covering:
    - Collection creation (Success and Name uniqueness per user validation)
    - Collection detail retrieval
    - Collection update (PATCH)
    - Collection deletion
    """

    def setUp(self):
        super().setUp()
        self.authenticate_user()

    def test_collection_crud_workflow(self):
        collections_url = "/api/collections/"

        # 1. CREATE Collection
        payload = {
            "name": "My Engineering Docs",
            "description": "All files regarding software engineering design plans."
        }
        response = self.client.post(collections_url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "My Engineering Docs")
        self.assertEqual(response.data["description"], "All files regarding software engineering design plans.")
        collection_id = response.data["id"]

        # Verify duplication validation: Same user cannot create another collection with the same name
        response_dup = self.client.post(collections_url, payload)
        self.assertEqual(response_dup.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response_dup.data)

        # 2. READ Collection Detail
        detail_url = f"/api/collections/{collection_id}/"
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "My Engineering Docs")

        # 3. UPDATE Collection Detail
        patch_payload = {
            "name": "Updated Engineering Docs",
            "description": "New updated description."
        }
        response = self.client.patch(detail_url, patch_payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Updated Engineering Docs")
        self.assertEqual(response.data["description"], "New updated description.")

        # 4. DELETE Collection
        response = self.client.delete(detail_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Collection.objects.filter(id=collection_id).exists())


class FileToCollectionTestCase(RapidRiseAPITestCase):
    """
    Test suite for File mapping to Collections, covering:
    - Adding a File to a Collection
    - Reading/Listing Files within a Collection
    - Removing a File from a Collection
    """

    def setUp(self):
        super().setUp()
        self.authenticate_user()
        # Create a dummy File and Collection
        self.file = File.objects.create(
            user=self.user,
            file=SimpleUploadedFile("dummy.txt", b"dummy content"),
            original_name="dummy.txt",
            file_size=13,
            content_type="text/plain",
            checksum="dummy_sum"
        )
        self.collection = Collection.objects.create(
            user=self.user,
            name="Test Collection"
        )

    def test_file_to_collection_workflow(self):
        # 1. Add file to collection
        url = f"/api/collections/{self.collection.id}/files/{self.file.id}/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(CollectionFile.objects.filter(collection=self.collection, file=self.file).exists())

        # 2. Get files inside the collection
        list_url = f"/api/collections/{self.collection.id}/files/"
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["file_name"], "dummy.txt")

        # 3. Remove file from collection
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(CollectionFile.objects.filter(collection=self.collection, file=self.file).exists())


class ProjectThreadTestCase(RapidRiseAPITestCase):
    """
    Test suite for Project Threads, covering:
    - Creating a thread successfully
    - Validation checks (e.g. duplicate titles, empty titles)
    """

    def setUp(self):
        super().setUp()
        self.authenticate_user()

    def test_create_thread_workflow(self):
        url = reverse("files:thread-list-create")

        # 1. CREATE Thread successfully
        payload = {
            "title": "Quantum Computation Research",
            "description": "A research thread on quantum computing and algorithms."
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Quantum Computation Research")
        self.assertEqual(response.data["description"], "A research thread on quantum computing and algorithms.")
        self.assertTrue(ProjectThread.objects.filter(title="Quantum Computation Research").exists())

        # 2. Validation check: Duplicate thread title for the same user
        response_dup = self.client.post(url, payload)
        self.assertEqual(response_dup.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("title", response_dup.data)

        # 3. Validation check: Blank/empty title
        response_blank = self.client.post(url, {"title": "  ", "description": ""})
        self.assertEqual(response_blank.status_code, status.HTTP_400_BAD_REQUEST)
