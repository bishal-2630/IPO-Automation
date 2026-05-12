import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/account.dart';

class ApiService {
  static const String baseUrl = 'https://bishal26-ipo-automation.hf.space/api';

  Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('token');
  }

  Future<void> saveToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('token', token);
  }

  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('token');
  }

  Future<bool> register(String username, String password, String email, String firstName, String lastName) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/register/'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'username': username,
        'password': password,
        'email': email,
        'first_name': firstName,
        'last_name': lastName,
      }),
    );
    if (response.statusCode == 201) {
      final data = json.decode(response.body);
      await saveToken(data['token']);
      return true;
    }
    return false;
  }

  Future<bool> login(String username, String password) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/login/'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({'username': username, 'password': password}),
    );
    if (response.statusCode == 200) {
      final data = json.decode(response.body);
      await saveToken(data['token']);
      return true;
    }
    return false;
  }

  Future<List<Account>> getAccounts() async {
    final token = await getToken();
    final response = await http.get(
      Uri.parse('$baseUrl/accounts/'),
      headers: {'Authorization': 'Token $token'},
    );
    if (response.statusCode == 200) {
      List jsonResponse = json.decode(response.body);
      return jsonResponse.map((data) => Account.fromJson(data)).toList();
    } else {
      throw Exception('Failed to load accounts: status ${response.statusCode}');
    }
  }

  Future<List<dynamic>> getLogs() async {
    final token = await getToken();
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/logs/'),
        headers: {'Authorization': 'Token $token'},
      );
      if (response.statusCode == 200) {
        return json.decode(response.body);
      } else {
        throw Exception('Failed to fetch logs (${response.statusCode})');
      }
    } catch (e) {
      rethrow;
    }
  }

  Future<void> addAccount(Map<String, dynamic> accountData) async {
    final token = await getToken();
    final response = await http.post(
      Uri.parse('$baseUrl/accounts/'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token $token'
      },
      body: json.encode(accountData),
    );
    if (response.statusCode != 201) {
      throw Exception('Failed to add account: ${response.body}');
    }
  }

  Future<void> updateAccount(int id, Map<String, dynamic> data) async {
    final token = await getToken();
    final response = await http.patch(
      Uri.parse('$baseUrl/accounts/$id/'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token $token'
      },
      body: json.encode(data),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to update account: ${response.body}');
    }
  }

  Future<void> deleteAccount(int id) async {
    final token = await getToken();
    final response = await http.delete(
      Uri.parse('$baseUrl/accounts/$id/'),
      headers: {'Authorization': 'Token $token'},
    );
    if (response.statusCode != 204) {
      throw Exception('Failed to delete account: ${response.body}');
    }
  }

  Future<void> saveFcmToken(String fcmToken, String deviceId) async {
    final token = await getToken();
    if (token == null) return;

    await http.post(
      Uri.parse('$baseUrl/fcm-tokens/'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token $token'
      },
      body: json.encode({
        'token': fcmToken,
        'device_id': deviceId,
      }),
    );
  }

  Future<void> deleteLog(int id) async {
    final token = await getToken();
    final response = await http.delete(
      Uri.parse('$baseUrl/logs/$id/'),
      headers: {'Authorization': 'Token $token'},
    );
    if (response.statusCode != 204) {
      throw Exception('Failed to delete log');
    }
  }

  Future<void> markLogsAsRead() async {
    final token = await getToken();
    await http.post(
      Uri.parse('$baseUrl/logs/mark-as-read/'),
      headers: {'Authorization': 'Token $token'},
    );
  }

  Future<Map<String, dynamic>> getUserProfile() async {
    final token = await getToken();
    final response = await http.get(
      Uri.parse('$baseUrl/auth/profile/'),
      headers: {'Authorization': 'Token $token'},
    );
    if (response.statusCode == 200) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to fetch profile');
    }
  }

  Future<void> deleteUserAccount() async {
    final token = await getToken();
    final response = await http.delete(
      Uri.parse('$baseUrl/auth/delete-account/'),
      headers: {'Authorization': 'Token $token'},
    );
    if (response.statusCode != 204) {
      throw Exception('Failed to delete user account');
    }
  }

  Future<void> requestPasswordReset(String email) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/password-reset-request/'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({'email': email}),
    );
    if (response.statusCode != 200) {
      final error = json.decode(response.body)['error'] ?? 'Failed to send OTP';
      throw Exception(error);
    }
  }

  Future<void> confirmPasswordReset(String email, String otp, String newPassword) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/password-reset-confirm/'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'email': email,
        'otp': otp,
        'new_password': newPassword,
      }),
    );
    if (response.statusCode != 200) {
      final error = json.decode(response.body)['error'] ?? 'Failed to reset password';
      throw Exception(error);
    }
  }
}
